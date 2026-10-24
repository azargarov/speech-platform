package texttransform

import (
	"os"
	"testing"
)

func TestMain(m *testing.M) {
	_ = os.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	os.Exit(m.Run())
}
