package gateway

import (
	"os"
	"testing"
)

type unreadyState struct{}

func (unreadyState) Ready() bool { return false }

func TestMain(m *testing.M) {
	_ = os.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	os.Exit(m.Run())
}
