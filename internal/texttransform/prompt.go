package texttransform

import (
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"strings"
	"unicode/utf8"
)

const maxPromptFileBytes = 64 * 1024

type promptSnapshot struct {
	text   string
	sha256 string
}

func loadPrompt(path string) (*promptSnapshot, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("prompt file could not be read")
	}
	defer file.Close()

	data, err := io.ReadAll(io.LimitReader(file, maxPromptFileBytes+1))
	if err != nil || len(data) > maxPromptFileBytes || !utf8.Valid(data) {
		return nil, fmt.Errorf("prompt file is empty, invalid UTF-8, unreadable, or exceeds %d bytes", maxPromptFileBytes)
	}
	text := strings.TrimSuffix(string(data), "\n")
	text = strings.TrimSuffix(text, "\r")
	if strings.TrimSpace(text) == "" {
		return nil, fmt.Errorf("prompt file is empty, invalid UTF-8, unreadable, or exceeds %d bytes", maxPromptFileBytes)
	}
	hash := sha256.Sum256([]byte(text))
	return &promptSnapshot{text: text, sha256: fmt.Sprintf("%x", hash)}, nil
}
