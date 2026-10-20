package gateway

import (
	"bytes"
	"crypto/subtle"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"speech-platform/internal/transport"
)

type Readiness interface{ Ready() bool }
type Foundation struct{}

func (Foundation) Ready() bool { return false }

type STTProxy struct {
	BaseURL string
	Token   string
	Timeout time.Duration
	Client  *http.Client
}

func NewSTTProxy(baseURL, token string, timeout time.Duration) *STTProxy {
	return &STTProxy{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, Timeout: timeout, Client: &http.Client{Timeout: timeout + 5*time.Second}}
}

func (p *STTProxy) Ready() bool {
	if p == nil || p.Client == nil {
		return false
	}
	r, err := p.Client.Get(p.BaseURL + "/readyz")
	if err != nil {
		return false
	}
	defer r.Body.Close()
	return r.StatusCode == http.StatusOK
}

func Handler(state Readiness, maxBytes int64) http.Handler {
	return HandlerWithSTT(state, maxBytes, nil)
}

func HandlerWithSTT(state Readiness, maxBytes int64, stt *STTProxy) http.Handler {
	mux := http.NewServeMux()
	requestSlots := make(chan struct{}, 4)
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		ready := 0
		if state.Ready() {
			ready = 1
		}
		_, _ = fmt.Fprintf(w, "# HELP speech_ready Whether this component can serve inference.\n# TYPE speech_ready gauge\nspeech_ready %d\n", ready)
	})
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		transport.JSON(w, 200, map[string]string{"status": "alive"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, _ *http.Request) {
		if !state.Ready() {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "STT worker is unavailable"})
			return
		}
		transport.JSON(w, 200, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("/v1/stt/transcriptions", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			transport.JSON(w, 405, transport.Error{Code: "method_not_allowed", Message: "POST is required"})
			return
		}
		if stt != nil && stt.Token != "" && !validBearer(r.Header.Get("Authorization"), stt.Token) {
			transport.JSON(w, 401, transport.Error{Code: "unauthorized", Message: "valid bearer token required"})
			return
		}
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data;") {
			transport.JSON(w, 415, transport.Error{Code: "unsupported_media_type", Message: "multipart/form-data is required"})
			return
		}
		select {
		case requestSlots <- struct{}{}:
			defer func() { <-requestSlots }()
		default:
			w.Header().Set("Retry-After", "2")
			transport.JSON(w, 429, transport.Error{Code: "overloaded", Message: "Gateway request capacity is full"})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
		body, err := io.ReadAll(r.Body)
		if err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
				return
			}
			transport.JSON(w, 400, transport.Error{Code: "invalid_request_body", Message: "request body could not be read"})
			return
		}
		if stt == nil {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "STT worker is unavailable"})
			return
		}
		upstream, err := http.NewRequestWithContext(r.Context(), http.MethodPost, stt.BaseURL+"/internal/v1/transcriptions", bytes.NewReader(body))
		if err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request could not be forwarded"})
			return
		}
		upstream.Header.Set("Content-Type", r.Header.Get("Content-Type"))
		upstream.Header.Set("X-Request-Timeout-Ms", fmt.Sprint(stt.Timeout.Milliseconds()))
		response, err := stt.Client.Do(upstream)
		if err != nil {
			transport.JSON(w, 503, transport.Error{Code: "worker_unavailable", Message: "STT worker could not complete the request"})
			return
		}
		defer response.Body.Close()
		responseBody, err := io.ReadAll(io.LimitReader(response.Body, 2*1024*1024+1))
		if err != nil || len(responseBody) > 2*1024*1024 {
			transport.JSON(w, 502, transport.Error{Code: "invalid_worker_response", Message: "STT worker returned an invalid response"})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(response.StatusCode)
		_, _ = w.Write(responseBody)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		transport.JSON(w, 404, transport.Error{Code: "not_found", Message: "endpoint unavailable"})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/stt/transcriptions" && r.ContentLength > maxBytes {
			transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
			return
		}
		mux.ServeHTTP(w, r)
	})
}

func validBearer(header, token string) bool {
	if len(header) < 8 || !strings.EqualFold(header[:7], "Bearer ") {
		return false
	}
	got := strings.TrimSpace(header[7:])
	if len(got) != len(token) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(got), []byte(token)) == 1
}
