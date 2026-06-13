package writers

import (
	"context"
	"fmt"
	"strings"

	"termpipe-go-mcp/pkg/tools/helpers"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func RegisterTools(s *server.MCPServer) {
	// insert_lines
	insertTool := mcp.NewTool("insert_lines",
		mcp.WithDescription("Insert lines BEFORE line_number (0-based)."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithNumber("line_number", mcp.Required()),
		mcp.WithString("content", mcp.Required()),
		mcp.WithBoolean("dry_run"),
	)
	s.AddTool(insertTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		lineNum, _ := request.RequireInt("line_number")
		content, _ := request.RequireString("content")
		dryRun := request.GetBool("dry_run", false)

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		oldCount := len(lines)
		if lineNum < 0 { lineNum = 0 }
		if lineNum > len(lines) { lineNum = len(lines) }

		content = strings.TrimSuffix(content, "\n")
		newLinesIn := strings.Split(content, "\n")

		var newLines []string
		newLines = append(newLines, lines[:lineNum]...)
		newLines = append(newLines, newLinesIn...)
		newLines = append(newLines, lines[lineNum:]...)

		diff := helpers.GenerateDiff(lines, newLines)

		if dryRun {
			out := fmt.Sprintf("🔍 Dry run — would insert %d line(s) before line %d\n\n```diff\n%s\n```\n\nFile NOT modified.", len(newLinesIn), lineNum, diff)
			return mcp.NewToolResultText(out), nil
		}

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		out := fmt.Sprintf("✅ Inserted %d line(s) before line %d\n%s\n\n```diff\n%s\n```", len(newLinesIn), lineNum, helpers.LineDeltaSummary(oldCount, len(newLines), lineNum), diff)
		return mcp.NewToolResultText(out), nil
	})

	// delete_lines
	deleteTool := mcp.NewTool("delete_lines",
		mcp.WithDescription("Delete lines start_line..end_line-1 (0-based, end exclusive)."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithNumber("start_line", mcp.Required()),
		mcp.WithNumber("end_line", mcp.Required()),
		mcp.WithBoolean("dry_run"),
	)
	s.AddTool(deleteTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		startLine, _ := request.RequireInt("start_line")
		endLine, _ := request.RequireInt("end_line")
		dryRun := request.GetBool("dry_run", false)

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		oldCount := len(lines)
		if startLine < 0 || startLine >= oldCount {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: start_line %d out of range]", startLine)), nil
		}

		deleted := lines[startLine:endLine]
		var newLines []string
		newLines = append(newLines, lines[:startLine]...)
		newLines = append(newLines, lines[endLine:]...)

		diff := helpers.GenerateDiff(lines, newLines)

		if dryRun {
			out := fmt.Sprintf("🔍 Dry run — would delete lines %d–%d\n(%d line(s))\n\n```diff\n%s\n```\n\nFile NOT modified.", startLine, endLine-1, len(deleted), diff)
			return mcp.NewToolResultText(out), nil
		}

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		out := fmt.Sprintf("✅ Deleted %d line(s) (%d–%d)\n%s\n\n```diff\n%s\n```", len(deleted), startLine, endLine-1, helpers.LineDeltaSummary(oldCount, len(newLines), startLine), diff)
		return mcp.NewToolResultText(out), nil
	})

	// overwrite_lines
	overwriteTool := mcp.NewTool("overwrite_lines",
		mcp.WithDescription("Replace a contiguous block of lines with new content."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithNumber("start_line", mcp.Required()),
		mcp.WithNumber("end_line", mcp.Required()),
		mcp.WithString("content", mcp.Required()),
		mcp.WithBoolean("dry_run"),
	)
	s.AddTool(overwriteTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		startLine, _ := request.RequireInt("start_line")
		endLine, _ := request.RequireInt("end_line")
		content, _ := request.RequireString("content")
		dryRun := request.GetBool("dry_run", false)

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		oldCount := len(lines)

		if startLine < 0 || startLine >= oldCount {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: start_line %d out of range]", startLine)), nil
		}
		if endLine < startLine {
			return mcp.NewToolResultText("[Error: end_line must be >= start_line]"), nil
		}

		content = strings.TrimSuffix(content, "\n")
		newLinesIn := strings.Split(content, "\n")

		var newLines []string
		newLines = append(newLines, lines[:startLine]...)
		newLines = append(newLines, newLinesIn...)
		newLines = append(newLines, lines[endLine:]...)

		oldReplaced := endLine - startLine
		diff := helpers.GenerateDiff(lines, newLines)

		if dryRun {
			out := fmt.Sprintf("🔍 Dry run — would replace lines %d–%d\n(%d → %d lines)\n\n```diff\n%s\n```\n\nFile NOT modified.", startLine, endLine-1, oldReplaced, len(newLinesIn), diff)
			return mcp.NewToolResultText(out), nil
		}

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		out := fmt.Sprintf("✅ Replaced lines %d–%d (%d → %d lines)\n%s\n\n```diff\n%s\n```", startLine, endLine-1, oldReplaced, len(newLinesIn), helpers.LineDeltaSummary(oldCount, len(newLines), startLine), diff)
		return mcp.NewToolResultText(out), nil
	})

	// patch_line
	patchTool := mcp.NewTool("patch_line",
		mcp.WithDescription("Replace a substring within a single known line."),
		mcp.WithString("path", mcp.Required()),
		mcp.WithNumber("line_number", mcp.Required()),
		mcp.WithString("old_text", mcp.Required()),
		mcp.WithString("new_text", mcp.Required()),
		mcp.WithBoolean("replace_all"),
		mcp.WithBoolean("dry_run"),
	)
	s.AddTool(patchTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		path, _ := request.RequireString("path")
		lineNum, _ := request.RequireInt("line_number")
		oldText, _ := request.RequireString("old_text")
		newText, _ := request.RequireString("new_text")
		replaceAll := request.GetBool("replace_all", false)
		dryRun := request.GetBool("dry_run", false)

		lines, err := helpers.ReadFileLines(path)
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		if lineNum < 0 || lineNum >= len(lines) {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: Line %d out of range]", lineNum)), nil
		}

		line := lines[lineNum]
		if !strings.Contains(line, oldText) {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: Text not found on line %d]", lineNum)), nil
		}

		count := strings.Count(line, oldText)
		newLine := line
		if replaceAll || count == 1 {
			newLine = strings.ReplaceAll(line, oldText, newText)
		} else {
			newLine = strings.Replace(line, oldText, newText, 1)
		}

		var newLines []string
		newLines = append(newLines, lines...)
		newLines[lineNum] = newLine

		diff := helpers.GenerateDiff(lines, newLines)
		inline := helpers.GenerateInlineDiff(line, newLine)

		if dryRun {
			out := fmt.Sprintf("🔍 Dry run — would modify line %d\n\n📐 %s\nBefore: %s\nAfter:  %s\n\n```diff\n%s\n```\n\nFile NOT modified.", lineNum, inline, strings.TrimSpace(line), strings.TrimSpace(newLine), diff)
			return mcp.NewToolResultText(out), nil
		}

		if err := helpers.AtomicWrite(path, newLines); err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}

		note := ""
		if count > 1 {
			if replaceAll {
				note = fmt.Sprintf(" (replaced all %d occurrence(s))", count)
			} else {
				note = fmt.Sprintf(" (replaced first of %d occurrence(s))", count)
			}
		}

		out := fmt.Sprintf("✅ Line %d%s\n📐 %s\nBefore: %s\nAfter:  %s", lineNum, note, inline, strings.TrimSpace(line), strings.TrimSpace(newLine))
		return mcp.NewToolResultText(out), nil
	})
}
