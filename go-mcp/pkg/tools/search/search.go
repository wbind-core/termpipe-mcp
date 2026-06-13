package search

import (
	"context"
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

type searchSession struct {
	Type      string
	Pattern   string
	Results   []string
	Path      string
	CreatedAt time.Time
}

var (
	activeSearches = make(map[string]searchSession)
	searchesMu     sync.Mutex
	hasRg          bool
)

const (
	searchTTLSecs = 3600
	searchMax     = 50
)

func init() {
	_, err := exec.LookPath("rg")
	hasRg = err == nil
}

func evictSearches() {
	searchesMu.Lock()
	defer searchesMu.Unlock()

	now := time.Now()
	for k, v := range activeSearches {
		if now.Sub(v.CreatedAt).Seconds() > searchTTLSecs {
			delete(activeSearches, k)
		}
	}

	for len(activeSearches) >= searchMax {
		var oldestKey string
		var oldestTime time.Time
		first := true
		for k, v := range activeSearches {
			if first || v.CreatedAt.Before(oldestTime) {
				oldestTime = v.CreatedAt
				oldestKey = k
				first = false
			}
		}
		delete(activeSearches, oldestKey)
	}
}

func RegisterTools(s *server.MCPServer) {
	// start_search
	startSearchTool := mcp.NewTool("start_search",
		mcp.WithDescription("Start a streaming search."),
		mcp.WithString("pattern", mcp.Required(), mcp.Description("What to search for")),
		mcp.WithString("path", mcp.Description("Root directory")),
		mcp.WithString("searchType", mcp.Description("files or content")),
		mcp.WithString("filePattern", mcp.Description("Filter to specific file types")),
		mcp.WithBoolean("ignoreCase", mcp.Description("Case-insensitive search")),
		mcp.WithBoolean("literalSearch", mcp.Description("Exact string matching")),
		mcp.WithNumber("maxResults", mcp.Description("Maximum results")),
		mcp.WithNumber("contextLines", mcp.Description("Lines of context around matches")),
		mcp.WithNumber("timeout_ms", mcp.Description("Timeout in milliseconds")),
	)
	s.AddTool(startSearchTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		pattern, _ := request.RequireString("pattern")
		path := request.GetString("path", ".")
		searchType := request.GetString("searchType", "content")
		filePattern := request.GetString("filePattern", "")
		ignoreCase := request.GetBool("ignoreCase", true)
		maxResults := request.GetInt("maxResults", 100)
		contextLines := request.GetInt("contextLines", 0)
		timeoutMs := request.GetInt("timeout_ms", 30000)

		sessionID := fmt.Sprintf("search_%s", time.Now().Format("20060102_150405_000000"))

		absPath, _ := filepath.Abs(path)

		timeoutCtx, cancel := context.WithTimeout(ctx, time.Duration(timeoutMs)*time.Millisecond)
		defer cancel()

		var results []string

		if searchType == "files" {
			var args []string
			args = append(args, absPath, "-type", "f")
			if filePattern != "" {
				args = append(args, "-name", filePattern)
			}
			cmd := exec.CommandContext(timeoutCtx, "find", args...)
			out, _ := cmd.CombinedOutput()
			
			files := strings.Split(strings.TrimSpace(string(out)), "\n")
			for _, f := range files {
				if f != "" && strings.Contains(strings.ToLower(f), strings.ToLower(pattern)) {
					results = append(results, f)
					if len(results) >= maxResults {
						break
					}
				}
			}
		} else {
			var cmd *exec.Cmd
			if hasRg {
				args := []string{"--color=never"}
				if ignoreCase {
					args = append(args, "-i")
				}
				if contextLines > 0 {
					args = append(args, "-A", fmt.Sprintf("%d", contextLines), "-B", fmt.Sprintf("%d", contextLines))
				}
				if filePattern != "" {
					args = append(args, "-g", filePattern)
				}
				args = append(args, "-e", pattern, absPath)
				cmd = exec.CommandContext(timeoutCtx, "rg", args...)
			} else {
				args := []string{"-r"}
				if filePattern != "" {
					args = append(args, "--include="+filePattern)
				} else {
					args = append(args, "--include=*")
				}
				if ignoreCase {
					args = append(args, "-i")
				}
				if contextLines > 0 {
					args = append(args, fmt.Sprintf("-A%d", contextLines), fmt.Sprintf("-B%d", contextLines))
				}
				args = append(args, pattern, absPath)
				cmd = exec.CommandContext(timeoutCtx, "grep", args...)
			}

			out, _ := cmd.CombinedOutput()
			lines := strings.Split(strings.TrimSpace(string(out)), "\n")
			
			for _, line := range lines {
				if line != "" {
					results = append(results, line)
					if len(results) >= maxResults {
						break
					}
				}
			}
		}

		evictSearches()
		searchesMu.Lock()
		activeSearches[sessionID] = searchSession{
			Type:      searchType,
			Pattern:   pattern,
			Results:   results,
			Path:      path,
			CreatedAt: time.Now(),
		}
		searchesMu.Unlock()

		return mcp.NewToolResultText(fmt.Sprintf("🔍 Search started: %s\n   Found %d results for '%s'\n   Use get_more_search_results('%s') to view", sessionID, len(results), pattern, sessionID)), nil
	})

	// get_more_search_results
	getMoreTool := mcp.NewTool("get_more_search_results",
		mcp.WithDescription("Get results from an active search."),
		mcp.WithString("sessionId", mcp.Required(), mcp.Description("Search ID from start_search")),
		mcp.WithNumber("offset", mcp.Description("Start index")),
		mcp.WithNumber("length", mcp.Description("Number of results to return")),
	)
	s.AddTool(getMoreTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		sessionID, _ := request.RequireString("sessionId")
		offset := request.GetInt("offset", 0)
		length := request.GetInt("length", 50)

		searchesMu.Lock()
		search, exists := activeSearches[sessionID]
		searchesMu.Unlock()

		if !exists {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: Search '%s' not found or expired]", sessionID)), nil
		}

		results := search.Results
		total := len(results)

		if offset >= total {
			return mcp.NewToolResultText(fmt.Sprintf("No more results (showing all %d total)", total)), nil
		}

		end := offset + length
		if end > total {
			end = total
		}
		selected := results[offset:end]
		remaining := total - end

		var output strings.Builder
		output.WriteString(fmt.Sprintf("Results %d to %d of %d\n", offset, end-1, total))
		if remaining > 0 {
			output.WriteString(fmt.Sprintf("(%d remaining)\n", remaining))
		}
		output.WriteString(strings.Repeat("-", 50) + "\n")

		for _, r := range selected {
			output.WriteString(r + "\n")
		}

		return mcp.NewToolResultText(output.String()), nil
	})

	// stop_search
	stopSearchTool := mcp.NewTool("stop_search",
		mcp.WithDescription("Stop and clean up a search."),
		mcp.WithString("sessionId", mcp.Required(), mcp.Description("Search ID to stop")),
	)
	s.AddTool(stopSearchTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		sessionID, _ := request.RequireString("sessionId")
		
		searchesMu.Lock()
		defer searchesMu.Unlock()
		
		if _, exists := activeSearches[sessionID]; exists {
			delete(activeSearches, sessionID)
			return mcp.NewToolResultText(fmt.Sprintf("✅ Search %s stopped and cleaned up", sessionID)), nil
		}
		
		return mcp.NewToolResultText(fmt.Sprintf("[Warning: Search '%s' not found]", sessionID)), nil
	})

	// list_searches
	listSearchesTool := mcp.NewTool("list_searches",
		mcp.WithDescription("List all active searches."),
	)
	s.AddTool(listSearchesTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		searchesMu.Lock()
		defer searchesMu.Unlock()

		if len(activeSearches) == 0 {
			return mcp.NewToolResultText("📭 No active searches"), nil
		}

		var output strings.Builder
		output.WriteString("Active Searches:\n" + strings.Repeat("=", 50) + "\n")
		
		for sid, search := range activeSearches {
			output.WriteString(fmt.Sprintf("\n  %s\n", sid))
			output.WriteString(fmt.Sprintf("  Pattern: %s\n", search.Pattern))
			output.WriteString(fmt.Sprintf("  Type: %s\n", search.Type))
			output.WriteString(fmt.Sprintf("  Results: %d\n", len(search.Results)))
		}

		return mcp.NewToolResultText(output.String()), nil
	})
}
