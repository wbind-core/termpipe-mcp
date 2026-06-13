package process

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

type ProcInfo struct {
	Command   string
	Process   *exec.Cmd
	Started   time.Time
	Blocked   bool
}

var (
	processes = make(map[int]*ProcInfo)
	procMu    sync.Mutex
)

func RegisterTools(s *server.MCPServer) {
	// list_sessions
	listTool := mcp.NewTool("list_sessions",
		mcp.WithDescription("List all active terminal sessions (running processes)."),
	)
	s.AddTool(listTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		procMu.Lock()
		defer procMu.Unlock()

		if len(processes) == 0 {
			return mcp.NewToolResultText("📭 No active sessions"), nil
		}

		var output strings.Builder
		output.WriteString(fmt.Sprintf("🔵 Active Sessions (%d):\n\n", len(processes)))
		for pid, info := range processes {
			status := "▶️  Running"
			if info.Blocked {
				status = "⏸️  Blocked"
			}
			output.WriteString(fmt.Sprintf("  PID %d: %s\n", pid, info.Command))
			output.WriteString(fmt.Sprintf("       Status: %s\n\n", status))
		}
		return mcp.NewToolResultText(output.String()), nil
	})

	// read_process_output
	readOutputTool := mcp.NewTool("read_process_output",
		mcp.WithDescription("Read output from a running process."),
		mcp.WithNumber("pid", mcp.Required()),
	)
	s.AddTool(readOutputTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		pid := request.GetInt("pid", 0)
		return mcp.NewToolResultText(fmt.Sprintf("[Error: read_process_output not fully implemented for Go port yet; PID %d]", pid)), nil
	})

	// interact_with_process
	interactTool := mcp.NewTool("interact_with_process",
		mcp.WithDescription("Send input to a running process."),
		mcp.WithNumber("pid", mcp.Required()),
		mcp.WithString("input", mcp.Required()),
	)
	s.AddTool(interactTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		pid := request.GetInt("pid", 0)
		return mcp.NewToolResultText(fmt.Sprintf("[Error: interact_with_process not fully implemented for Go port yet; PID %d]", pid)), nil
	})

	// force_terminate
	terminateTool := mcp.NewTool("force_terminate",
		mcp.WithDescription("Force terminate a running process by PID."),
		mcp.WithNumber("pid", mcp.Required()),
	)
	s.AddTool(terminateTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		pid := request.GetInt("pid", 0)
		
		procMu.Lock()
		if info, exists := processes[pid]; exists {
			if info.Process != nil && info.Process.Process != nil {
				info.Process.Process.Kill()
			}
			delete(processes, pid)
		}
		procMu.Unlock()
		
		syscall.Kill(pid, syscall.SIGKILL)
		return mcp.NewToolResultText(fmt.Sprintf("✅ Terminated process %d", pid)), nil
	})

	// list_processes
	listProcsTool := mcp.NewTool("list_processes",
		mcp.WithDescription("List all running processes (system-wide)."),
	)
	s.AddTool(listProcsTool, func(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		cmd := exec.Command("ps", "aux", "--sort=-%mem")
		out, err := cmd.CombinedOutput()
		if err != nil {
			return mcp.NewToolResultText(fmt.Sprintf("[Error: %v]", err)), nil
		}
		lines := strings.Split(strings.TrimSpace(string(out)), "\n")
		var output strings.Builder
		output.WriteString("🖥️  System Processes (sorted by memory):\n\n")
		
		end := 51
		if len(lines) < 51 { end = len(lines) }
		for i := 0; i < end; i++ {
			output.WriteString(lines[i] + "\n")
		}
		if len(lines) > 51 {
			output.WriteString(fmt.Sprintf("\n... and %d more (use 'ps aux' for full list)", len(lines)-51))
		}
		return mcp.NewToolResultText(output.String()), nil
	})
}
