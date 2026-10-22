package gateway

import (
	"bytes"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

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

type TTSProxy struct {
	BaseURL string
	Token   string
	Timeout time.Duration
	Client  *http.Client
}

func NewTTSProxy(baseURL, token string, timeout time.Duration) *TTSProxy {
	return &TTSProxy{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, Timeout: timeout, Client: &http.Client{Timeout: timeout + 5*time.Second}}
}

func (p *TTSProxy) Ready() bool {
	if p == nil || p.Client == nil {
		return false
	}
	r, err := (&http.Client{Timeout: 1500 * time.Millisecond}).Get(p.BaseURL + "/readyz")
	if err != nil {
		return false
	}
	defer r.Body.Close()
	return r.StatusCode == http.StatusOK
}

func NewSTTProxy(baseURL, token string, timeout time.Duration) *STTProxy {
	return &STTProxy{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, Timeout: timeout, Client: &http.Client{Timeout: timeout + 5*time.Second}}
}

func (p *STTProxy) Ready() bool {
	if p == nil || p.Client == nil {
		return false
	}
	r, err := (&http.Client{Timeout: 1500 * time.Millisecond}).Get(p.BaseURL + "/readyz")
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
	return HandlerWithWorkers(state, maxBytes, stt, nil)
}

type WorkersReadiness struct {
	STT *STTProxy
	TTS *TTSProxy
}

func (w WorkersReadiness) Ready() bool {
	if w.STT == nil {
		return false
	}
	if w.TTS == nil {
		return w.STT.Ready()
	}
	results := make(chan bool, 2)
	go func() { results <- w.STT.Ready() }()
	go func() { results <- w.TTS.Ready() }()
	return <-results && <-results
}

func NewWorkersReadiness(stt *STTProxy, tts *TTSProxy) WorkersReadiness {
	return WorkersReadiness{STT: stt, TTS: tts}
}

func HandlerWithWorkers(state Readiness, maxBytes int64, stt *STTProxy, tts *TTSProxy) http.Handler {
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
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "required inference worker is unavailable"})
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
	mux.HandleFunc("/v1/tts/speech", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			transport.JSON(w, 405, transport.Error{Code: "method_not_allowed", Message: "POST is required"})
			return
		}
		if tts != nil && tts.Token != "" && !validBearer(r.Header.Get("Authorization"), tts.Token) {
			transport.JSON(w, 401, transport.Error{Code: "unauthorized", Message: "valid bearer token required"})
			return
		}
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			transport.JSON(w, 415, transport.Error{Code: "unsupported_media_type", Message: "application/json is required"})
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
			} else {
				transport.JSON(w, 400, transport.Error{Code: "invalid_request_body", Message: "request body could not be read"})
			}
			return
		}
		var request struct {
			Text     string `json:"text"`
			Voice    string `json:"voice,omitempty"`
			Language string `json:"language"`
			Mode     string `json:"mode"`
		}
		decoder := json.NewDecoder(bytes.NewReader(body))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&request); err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request must contain only text, language, and mode"})
			return
		}
		var extra any
		if err := decoder.Decode(&extra); err != io.EOF {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "exactly one JSON object is required"})
			return
		}
		if strings.TrimSpace(request.Text) == "" || utf8.RuneCountInString(request.Text) > 10000 {
			transport.JSON(w, 400, transport.Error{Code: "invalid_text", Message: "text must contain 1..10000 characters"})
			return
		}
		if request.Voice == "" {
			request.Voice = "default"
		}
		if request.Voice != "default" {
			transport.JSON(w, 404, transport.Error{Code: "unknown_voice", Message: "unknown voice"})
			return
		}
		if request.Language == "" {
			request.Language = "auto"
		}
		if request.Language != "auto" && request.Language != "en" && request.Language != "ru" && request.Language != "sv" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_language", Message: "language must be auto, en, ru, or sv"})
			return
		}
		if request.Mode == "" {
			request.Mode = "quality"
		}
		if request.Mode != "quality" && request.Mode != "fast" && request.Mode != "auto" && request.Mode != "high_quality" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_mode", Message: "mode must be quality, fast, auto, or high_quality"})
			return
		}
		if tts == nil {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "TTS worker is unavailable"})
			return
		}
		encoded, err := json.Marshal(request)
		if err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request could not be forwarded"})
			return
		}
		upstream, err := http.NewRequestWithContext(r.Context(), http.MethodPost, tts.BaseURL+"/internal/v1/speech", bytes.NewReader(encoded))
		if err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request could not be forwarded"})
			return
		}
		upstream.Header.Set("Content-Type", "application/json")
		upstream.Header.Set("X-Request-Timeout-Ms", fmt.Sprint(tts.Timeout.Milliseconds()))
		response, err := tts.Client.Do(upstream)
		if err != nil {
			transport.JSON(w, 503, transport.Error{Code: "worker_unavailable", Message: "TTS worker could not complete the request"})
			return
		}
		defer response.Body.Close()
		maxAudio := 64 * 1024 * 1024
		responseBody, err := io.ReadAll(io.LimitReader(response.Body, int64(maxAudio+1)))
		if err != nil || len(responseBody) > maxAudio {
			transport.JSON(w, 502, transport.Error{Code: "invalid_worker_response", Message: "TTS worker returned an invalid response"})
			return
		}
		contentType := response.Header.Get("Content-Type")
		if response.StatusCode == 200 && contentType != "audio/wav" {
			transport.JSON(w, 502, transport.Error{Code: "invalid_worker_response", Message: "TTS worker returned an unsupported audio format"})
			return
		}
		w.Header().Set("Content-Type", contentType)
		w.WriteHeader(response.StatusCode)
		_, _ = w.Write(responseBody)
	})
	mux.HandleFunc("GET /v1/tts/voices", func(w http.ResponseWriter, r *http.Request) {
		if tts != nil && tts.Token != "" && !validBearer(r.Header.Get("Authorization"), tts.Token) {
			transport.JSON(w, 401, transport.Error{Code: "unauthorized", Message: "valid bearer token required"})
			return
		}
		if tts == nil {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "TTS worker is unavailable"})
			return
		}
		request, err := http.NewRequestWithContext(r.Context(), http.MethodGet, tts.BaseURL+"/internal/v1/voices", nil)
		if err != nil {
			transport.JSON(w, 503, transport.Error{Code: "worker_unavailable", Message: "TTS worker could not complete the request"})
			return
		}
		response, err := tts.Client.Do(request)
		if err != nil {
			transport.JSON(w, 503, transport.Error{Code: "worker_unavailable", Message: "TTS worker could not complete the request"})
			return
		}
		defer response.Body.Close()
		body, err := io.ReadAll(io.LimitReader(response.Body, 64*1024+1))
		if err != nil || len(body) > 64*1024 {
			transport.JSON(w, 502, transport.Error{Code: "invalid_worker_response", Message: "TTS worker returned an invalid response"})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(response.StatusCode)
		_, _ = w.Write(body)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		transport.JSON(w, 404, transport.Error{Code: "not_found", Message: "endpoint unavailable"})
	})
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if (r.URL.Path == "/v1/stt/transcriptions" || r.URL.Path == "/v1/tts/speech") && r.ContentLength > maxBytes {
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
