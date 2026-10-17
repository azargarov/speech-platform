package gateway

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
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

func TestRequestSizeLimit(t *testing.T) {
	h := Handler(Foundation{}, 4)
	for _, tc := range []struct {
		name string
		body string
		want int
	}{{"at_limit", "1234", 404}, {"over_limit", "12345", 413}, {"unknown_length_over_limit", "12345", 413}} {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/v1/stt/transcriptions", strings.NewReader(tc.body))
			if tc.name == "unknown_length_over_limit" {
				r.ContentLength = -1
			}
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code != tc.want {
				t.Fatalf("status=%d want=%d body=%s", w.Code, tc.want, w.Body.String())
			}
			if tc.want == 413 {
				var response map[string]string
				if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil || response["code"] != "request_too_large" {
					t.Fatalf("response=%q error=%v", w.Body.String(), err)
				}
			}
		})
	}
}
