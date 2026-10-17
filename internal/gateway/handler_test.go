package gateway

import (
	"net/http/httptest"
	"testing"
)

func TestFoundation(t *testing.T) {
	h := Handler(Foundation{}, 1024)
	for _, tc := range []struct {
		method, path string
		status       int
	}{{"GET", "/metrics", 200}, {"GET", "/healthz", 200}, {"GET", "/readyz", 503}, {"POST", "/v1/stt/transcriptions", 404}, {"POST", "/v1/tts/speech", 404}, {"GET", "/v1/stt/models", 404}, {"GET", "/v1/tts/voices", 404}} {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.status {
			t.Fatalf("%s: %d", tc.path, w.Code)
		}
	}
}
