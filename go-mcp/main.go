package main

import (
	"fmt"

	"termpipe-go-mcp/pkg/tools/process"
	"termpipe-go-mcp/pkg/tools/readers"
	"termpipe-go-mcp/pkg/tools/replacers"
	"termpipe-go-mcp/pkg/tools/search"
	"termpipe-go-mcp/pkg/tools/termf"
	"termpipe-go-mcp/pkg/tools/writers"

	"github.com/mark3labs/mcp-go/server"
)

func main() {
	// Create an MCP Server
	mcpServer := server.NewMCPServer(
		"termpipe-mcp",
		"1.0.0",
		server.WithToolCapabilities(true),
	)

	// Register Ported Tools
	readers.RegisterTools(mcpServer)
	search.RegisterTools(mcpServer)
	writers.RegisterTools(mcpServer)
	replacers.RegisterTools(mcpServer)
	process.RegisterTools(mcpServer)
	termf.RegisterTools(mcpServer)

	// Start standard IO server
	fmt.Println("Starting TermPipe Go MCP Server...")
	if err := server.ServeStdio(mcpServer); err != nil {
		fmt.Printf("Server error: %v\n", err)
	}
}
