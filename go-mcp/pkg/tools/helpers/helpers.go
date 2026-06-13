package helpers

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/pmezard/go-difflib/difflib"
)

func ReadFileLines(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return strings.Split(string(data), "\n"), nil
}

func AtomicWrite(path string, lines []string) error {
	content := strings.Join(lines, "\n")
	dir := filepath.Dir(path)
	tmpFile, err := os.CreateTemp(dir, ".surgical_*")
	if err != nil {
		return err
	}
	tmpName := tmpFile.Name()
	defer os.Remove(tmpName)

	if _, err := tmpFile.WriteString(content); err != nil {
		tmpFile.Close()
		return err
	}
	if err := tmpFile.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

func GenerateDiff(oldLines, newLines []string) string {
	diff := difflib.UnifiedDiff{
		A:        oldLines,
		B:        newLines,
		FromFile: "before",
		ToFile:   "after",
		Context:  3,
	}
	text, _ := difflib.GetUnifiedDiffString(diff)
	return strings.TrimSpace(text)
}

func GenerateInlineDiff(oldText, newText string) string {
	if oldText == newText {
		return oldText
	}
	return fmt.Sprintf("{- %s -}{+ %s +}", oldText, newText)
}

func LineDeltaSummary(oldCount, newCount, editStart int) string {
	delta := newCount - oldCount
	sign := fmt.Sprintf("%d", delta)
	if delta >= 0 {
		sign = fmt.Sprintf("+%d", delta)
	}
	msg := fmt.Sprintf("\n📊 File: %d → %d lines (delta: %s)", oldCount, newCount, sign)
	if delta != 0 {
		msg += fmt.Sprintf("\n⚠️  Line numbers from line %d onward shifted by %s", editStart, sign)
	}
	return msg
}

func FindSimilarLines(lines []string, target string) []string {
	return nil
}
