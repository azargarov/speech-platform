package gateway

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"speech-platform/internal/transport"
)

// Readiness is injected so later milestones can supply authenticated routing and worker state.
type Readiness interface{ Ready() bool }
type Foundation struct{}

func (Foundation) Ready() bool { return false }
func Handler(state Readiness, maxBytes int64) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		ready := 0
		if state.Ready() {
			ready = 1
		}
		_, _ = fmt.Fprintf(w, "# HELP speech_ready Whether this component can serve inference.\n# TYPE speech_ready gauge\nspeech_ready %d\n", ready)
	})

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		transport.JSON(w, 200, map[string]string{"status": "alive"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if !state.Ready() {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "authenticated inference routing unavailable"})
			return
		}
		transport.JSON(w, 200, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		transport.JSON(w, 404, transport.Error{Code: "not_found", Message: "endpoint unavailable"})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
		if _, err := io.Copy(io.Discard, r.Body); err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				transport.JSON(w, http.StatusRequestEntityTooLarge, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
				return
			}
			transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request_body", Message: "request body could not be read"})
			return
		}
		mux.ServeHTTP(w, r)
	})
}
