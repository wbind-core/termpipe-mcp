package replacers

import (
	"context"
	"fmt"
	"strings"

	"termpipe-go-mcp/pkg/tools/helpers"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func RegisterTools(s *server.MCPServer) {
	// smart_replace
	smartTool := mcp.NewTool("smart_replace",
		mcp.WithDescription("Content-addressed find-and-replace."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithString("old_text", mcp.Required()),
		mcp.WithString("new_text", mcp.Required()),
		mcp.WithNumber("expected_line"),
		mcp.WithBoolean("dry_run"),
	)
	s.AddTool(smartTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		oldText, _ := request.RequireString("old_text")
		newText, _ := request.RequireString("new_text")
		
		var expectedLine *int
		if el, ok := request.GetArguments()["expected_line"].(float64); ok {
			v := int(el)
			expectedLine = &v
		}
		dryRun := request.GetBool("dry_run", false)

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		content := strings.Join(lines, "\n")

		if !strings.Contains(content, oldText) {
			if strings.Contains(content, newText) && newText != oldText {
				return mcp.NewToolResultText("✅ Already done (old_text not found, new_text already present)\nℹ️  File was NOT modified."), nil
			}
			return mcp.NewToolResultText(fmt.Sprintf("[Error: Text not found]\n🔍 Searched: %s", oldText)), nil
		}

		occCount := strings.Count(content, oldText)
		if occCount > 1 {
			// Find line numbers of all occurrences
			var occLines []int
			searchPos := 0
			for i := 0; i < occCount; i++ {
				pos := strings.Index(content[searchPos:], oldText)
				if pos == -1 {
					break
				}
				pos += searchPos
				occLines = append(occLines, strings.Count(content[:pos], "\n"))
				searchPos = pos + 1
			}

			if expectedLine != nil {
				found := false
				for _, l := range occLines {
					if l == *expectedLine {
						found = true
						break
					}
				}
				if !found {
					return mcp.NewToolResultText(fmt.Sprintf("[Error: expected_line %d not found in occurrences %v]", *expectedLine, occLines)), nil
				}

				// Replace specific occurrence
				occIdx := -1
				for i, l := range occLines {
					if l == *expectedLine {
						occIdx = i
						break
					}
				}
				
				searchPos = 0
				var pos int
				for i := 0; i <= occIdx; i++ {
					idx := strings.Index(content[searchPos:], oldText)
					pos = searchPos + idx
					searchPos = pos + len(oldText)
				}

				newContent := content[:pos] + newText + content[pos+len(oldText):]
				newLines := strings.Split(newContent, "\n")
				oldCount := len(lines)

				if dryRun {
					diff := helpers.GenerateDiff(lines, newLines)
					return mcp.NewToolResultText(fmt.Sprintf("🔍 Dry run — occurrence at line %d would be replaced\n\n```diff\n%s\n```\n\nFile NOT modified.", *expectedLine, diff)), nil
				}

				if err := helpers.AtomicWrite(path, newLines); err != nil {
					return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
				}

				diff := helpers.GenerateDiff(lines, newLines)
				out := fmt.Sprintf("✅ Replaced occurrence at line %d\n%s\n\n```diff\n%s\n```", *expectedLine, helpers.LineDeltaSummary(oldCount, len(newLines), *expectedLine), diff)
				return mcp.NewToolResultText(out), nil
			} else {
				return mcp.NewToolResultText(fmt.Sprintf("[Ambiguous: %d occurrences on lines: %v]\n💡 Rerun with expected_line=<N> to target one.", occCount, occLines)), nil
			}
		}

		// Unique occurrence
		oldCount := len(lines)
		pos := strings.Index(content, oldText)
		startLineNo := strings.Count(content[:pos], "\n")
		newContent := strings.Replace(content, oldText, newText, 1)
		newLines := strings.Split(newContent, "\n")

		if dryRun {
			diff := helpers.GenerateDiff(lines, newLines)
			return mcp.NewToolResultText(fmt.Sprintf("🔍 Dry run — would replace at line %d\n\n```diff\n%s\n```\n\nFile NOT modified.", startLineNo, diff)), nil
		}

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		diff := helpers.GenerateDiff(lines, newLines)
		out := fmt.Sprintf("✅ Replaced at line %d\n%s\n\n```diff\n%s\n```", startLineNo, helpers.LineDeltaSummary(oldCount, len(newLines), startLineNo), diff)
		return mcp.NewToolResultText(out), nil
	})

	// remove_duplicates
	dedupTool := mcp.NewTool("remove_duplicates",
		mcp.WithDescription("Remove consecutive duplicate lines in a range."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithNumber("start_line", mcp.Required()),
		mcp.WithNumber("end_line", mcp.Required()),
	)
	s.AddTool(dedupTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		startLine, _ := request.RequireInt("start_line")
		endLine, _ := request.RequireInt("end_line")

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		oldCount := len(lines)
		if startLine < 0 || startLine >= oldCount {
			return mcp.NewToolResultText("[Error: start_line out of range]"), nil
		}
		if endLine > oldCount {
			endLine = oldCount
		}

		prefix := lines[:startLine]
		target := lines[startLine:endLine]
		suffix := lines[endLine:]

		if len(target) == 0 {
			return mcp.NewToolResultText("No lines to deduplicate"), nil
		}

		var processed []string
		processed = append(processed, target[0])
		for i := 1; i < len(target); i++ {
			if target[i] != processed[len(processed)-1] {
				processed = append(processed, target[i])
			}
		}

		var newLines []string
		newLines = append(newLines, prefix...)
		newLines = append(newLines, processed...)
		newLines = append(newLines, suffix...)

		removed := len(target) - len(processed)
		diff := helpers.GenerateDiff(lines, newLines)

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		out := fmt.Sprintf("✅ Removed %d duplicate(s)\n%s\n\n```diff\n%s\n```", removed, helpers.LineDeltaSummary(oldCount, len(newLines), startLine), diff)
		return mcp.NewToolResultText(out), nil
	})
}
