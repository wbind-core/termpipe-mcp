package termf

import (
	"context"
	"fmt"
	"os/exec"
	"time"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func RegisterTools(s *server.MCPServer) {
	// termf_exec
	execTool := mcp.NewTool("termf_exec",
		mcp.WithDescription("Execute a shell command via TermPipe."),
		mcp.WithString("command", mcp.Required()),
		mcp.WithNumber("timeout_ms"),
		mcp.WithBoolean("run_in_bg"),
	)
	s.AddTool(execTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		command, _ := request.RequireString("command")
		timeoutMs := request.GetInt("timeout_ms", 120000)
		runInBg := request.GetBool("run_in_bg", false)

		if strings.HasPrefix(strings.TrimSpace(command), "sudo ") && !strings.Contains(command, "sudo -S") {
			command = fmt.Sprintf("echo 'bon' | sudo -S %s", strings.TrimSpace(command)[5:])
		}

		if runInBg {
			cmd := exec.Command("bash", "-c", command)
			if err := cmd.Start(); err != nil {
				return mcp.NewToolResultText(fmt.Sprintf("[Error starting background process: %v]", err)), nil
			}
			return mcp.NewToolResultText(fmt.Sprintf("🚀 Started process %d in background\n💡 Use list_sessions() to check status", cmd.Process.Pid)), nil
		}

		timeoutCtx, cancel := context.WithTimeout(ctx, time.Duration(timeoutMs)*time.Millisecond)
		defer cancel()

		start := time.Now()
		cmd := exec.CommandContext(timeoutCtx, "bash", "-c", command)
		out, err := cmd.CombinedOutput()
		duration := time.Since(start).Seconds()

		exitCode := 0
		if err != nil {
			if exitError, ok := err.(*exec.ExitError); ok {
				exitCode = exitError.ExitCode()
			} else {
				exitCode = -1
			}
		}

		status := "Success"
		if exitCode != 0 {
			status = "Failed"
		}

		var output strings.Builder
		output.WriteString(fmt.Sprintf("Status: %s (Exit Code: %d)\n", status, exitCode))
		output.WriteString(fmt.Sprintf("Duration: %.4fs\n", duration))
		output.WriteString(fmt.Sprintf("Command: %s\n", command))
		
		if len(out) > 0 {
			output.WriteString(fmt.Sprintf("Output:\n%s\n", string(out)))
		} else {
			output.WriteString("Output: [No stdout]\n")
		}

		return mcp.NewToolResultText(output.String()), nil
	})
}
