package readers

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func RegisterTools(s *server.MCPServer) {
	// read_lines
	readLinesTool := mcp.NewTool("read_lines",
		mcp.WithDescription("Read specific line range from a file (0-based)."),
		mcp.WithString("path", mcp.Required(), mcp.Description("File path")),
		mcp.WithNumber("start_line", mcp.Required(), mcp.Description("Start line (0-based)")),
		mcp.WithNumber("end_line", mcp.Description("End line (exclusive)")),
	)
	s.AddTool(readLinesTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		startLine, _ := request.RequireInt("start_line")
		
		endLine := request.GetInt("end_line", startLine+1)

		data, err := os.ReadFile(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		lines := strings.Split(string(data), "\n")
		if startLine < 0 || startLine >= len(lines) {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: Line %d out of range (file has %d lines)]", startLine, len(lines))), nil
		}

		end := endLine
		if end > len(lines) {
			end = len(lines)
		}

		var output strings.Builder
		output.WriteString(fmt.Sprintf("Lines %d-%d of %s (total: %d):\n\n", startLine, end-1, path, len(lines)))
		for i := startLine; i < end; i++ {
			output.WriteString(fmt.Sprintf("%4d | %s\n", i, lines[i]))
		}

		return mcp.NewToolResultText(output.String()), nil
	})

	// find_in_file
	findInFileTool := mcp.NewTool("find_in_file",
		mcp.WithDescription("Find pattern in file with line numbers and optional context lines."),
		mcp.WithString("path", mcp.Required(), mcp.Description("File path")),
		mcp.WithString("pattern", mcp.Required(), mcp.Description("Search pattern")),
		mcp.WithNumber("max_matches", mcp.Description("Maximum matches")),
		mcp.WithNumber("context", mcp.Description("Context lines")),
	)
	s.AddTool(findInFileTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		pattern, _ := request.RequireString("pattern")
		pattern = strings.ToLower(pattern)
		
		maxMatches := request.GetInt("max_matches", 50)
		contextLines := request.GetInt("context", 0)

		data, err := os.ReadFile(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		lines := strings.Split(string(data), "\n")
		var matches []int
		for i, line := range lines {
			if strings.Contains(strings.ToLower(line), pattern) {
				matches = append(matches, i)
				if len(matches) >= maxMatches {
					break
				}
			}
		}

		if len(matches) == 0 {
			return mcp.NewToolResultText(fmt.Sprintf("No matches for: %s", pattern)), nil
		}

		var output strings.Builder
		output.WriteString(fmt.Sprintf("Found %d match(es) for '%s' (file: %d lines):\n\n", len(matches), pattern, len(lines)))
		for _, m := range matches {
			if contextLines > 0 {
				start := m - contextLines
				if start < 0 { start = 0 }
				end := m + contextLines + 1
				if end > len(lines) { end = len(lines) }
				
				output.WriteString(fmt.Sprintf("--- Line %d ---\n", m))
				for i := start; i < end; i++ {
					prefix := " "
					if i == m { prefix = "→" }
					output.WriteString(fmt.Sprintf("%s %4d | %s\n", prefix, i, lines[i]))
				}
				output.WriteString("\n")
			} else {
				line := lines[m]
				if len(line) > 80 { line = line[:80] }
				output.WriteString(fmt.Sprintf("Line %d: %s\n", m, strings.TrimSpace(line)))
			}
		}

		return mcp.NewToolResultText(output.String()), nil
	})

	// read_multiple_files
	readMultipleFilesTool := mcp.NewTool("read_multiple_files",
		mcp.WithDescription("Read contents of multiple files at once."),
		mcp.WithArray("paths", mcp.Required(), mcp.Description("List of file paths")),
	)
	
	s.AddTool(readMultipleFilesTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		paths, err := request.RequireStringSlice("paths")
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		var output strings.Builder
		for _, path := range paths {
			data, err := os.ReadFile(path)
			if err != nil {
				output.WriteString(fmt.Sprintf("=== %s ===\n[Error: %v]\n", path, err))
				continue
			}

			ext := strings.ToLower(filepath.Ext(path))
			isImage := ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".gif" || ext == ".webp" || ext == ".bmp"

			if isImage {
				b64 := base64.StdEncoding.EncodeToString(data)
				output.WriteString(fmt.Sprintf("=== %s ===\n[Image: %s (%d bytes)]\n", path, ext, len(b64)))
			} else {
				output.WriteString(fmt.Sprintf("=== %s ===\n%s\n", path, string(data)))
			}
		}

		return mcp.NewToolResultText(output.String()), nil
	})
}
