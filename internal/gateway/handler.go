package gateway

import (
	"bytes"
	"context"
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

const (
	maxTTSRequestBytes   int64 = 64 * 1024
	maxTextRequestBytes  int64 = 64 * 1024
	maxSSMLDocumentBytes       = 48 * 1024
)

func requestBodyLimit(path string, configured int64) int64 {
	if (path == "/v1/tts/speech" && configured > maxTTSRequestBytes) || (path == "/v1/text/transformations" && configured > maxTextRequestBytes) {
		if path == "/v1/text/transformations" {
			return maxTextRequestBytes
		}
		return maxTTSRequestBytes
	}
	return configured
}

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
	return HandlerWithWorkersAndText(state, maxBytes, stt, tts, nil)
}

func HandlerWithWorkersAndText(state Readiness, maxBytes int64, stt *STTProxy, tts *TTSProxy, text http.Handler) http.Handler {
	return HandlerWithWarmupContext(state, maxBytes, stt, tts, text, 180*time.Second, context.Background())
}

func HandlerWithWarmupContext(state Readiness, maxBytes int64, stt *STTProxy, tts *TTSProxy, text http.Handler, timeout time.Duration, warmupRoot context.Context) http.Handler {
	mux := http.NewServeMux()
	warmup := newWarmupCoordinator()
	warmupSlots := make(chan struct{}, 4)
	if timeout <= 0 {
		timeout = 180 * time.Second
	}
	if warmupRoot == nil {
		warmupRoot = context.Background()
	}
	requestSlots := make(chan struct{}, 4)
	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		ready := 0
		if state.Ready() {
			ready = 1
		}
		_, _ = fmt.Fprintf(w, "# HELP speech_ready Whether this component can serve inference.\n# TYPE speech_ready gauge\nspeech_ready %d\n", ready)
		if observable, ok := text.(interface{ Metrics() string }); ok {
			_, _ = io.WriteString(w, observable.Metrics())
		}
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
	mux.HandleFunc("/v1/models/warmup", func(w http.ResponseWriter, r *http.Request) {
		token := ""
		if stt != nil {
			token = stt.Token
		}
		if token == "" && tts != nil {
			token = tts.Token
		}
		serveWarmup(w, r, token, warmup, warmupSlots, stt, tts, text, timeout, warmupRoot)
	})
	if text == nil {
		mux.HandleFunc("/v1/text/transformations", func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodPost {
				transport.JSON(w, 405, transport.Error{Code: "method_not_allowed", Message: "POST is required"})
				return
			}
			transport.JSON(w, 503, transport.Error{Code: "text_transform_unavailable", Message: "text transformation is unavailable"})
		})
	} else {
		mux.Handle("/v1/text/transformations", text)
	}
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
		r.Body = http.MaxBytesReader(w, r.Body, requestBodyLimit(r.URL.Path, maxBytes))
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
		r.Body = http.MaxBytesReader(w, r.Body, requestBodyLimit(r.URL.Path, maxBytes))
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
			Text            string          `json:"text"`
			Voice           string          `json:"voice,omitempty"`
			Language        string          `json:"language"`
			Mode            string          `json:"mode"`
			InputFormat     json.RawMessage `json:"input_format"`
			AudioProcessing string          `json:"audio_processing"`
		}
		decoder := json.NewDecoder(bytes.NewReader(body))
		decoder.DisallowUnknownFields()
		if err := decoder.Decode(&request); err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request contains invalid or unsupported fields"})
			return
		}
		var extra any
		if err := decoder.Decode(&extra); err != io.EOF {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "exactly one JSON object is required"})
			return
		}
		inputFormat := "text"
		if request.InputFormat != nil {
			rawInputFormat := bytes.TrimSpace(request.InputFormat)
			if bytes.Equal(rawInputFormat, []byte("null")) || json.Unmarshal(rawInputFormat, &inputFormat) != nil {
				transport.JSON(w, 400, transport.Error{Code: "invalid_input_format", Message: "input_format must be text or ssml"})
				return
			}
		}
		if inputFormat != "text" && inputFormat != "ssml" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_input_format", Message: "input_format must be text or ssml"})
			return
		}
		if inputFormat == "ssml" && len([]byte(request.Text)) > maxSSMLDocumentBytes {
			transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "SSML document size limit exceeded"})
			return
		}
		if strings.TrimSpace(request.Text) == "" || (inputFormat == "text" && utf8.RuneCountInString(request.Text) > 10000) {
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
		if inputFormat == "ssml" && request.Language != "auto" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_language", Message: "SSML language is specified by speak and lang xml:lang attributes"})
			return
		}
		if request.Mode == "" {
			request.Mode = "quality"
		}
		if request.Mode != "quality" && request.Mode != "fast" && request.Mode != "auto" && request.Mode != "high_quality" && request.Mode != "extra_high_quality" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_mode", Message: "mode must be quality, fast, auto, high_quality, or extra_high_quality"})
			return
		}
		if request.AudioProcessing == "" {
			request.AudioProcessing = "none"
		}
		if request.AudioProcessing != "none" && request.AudioProcessing != "gentle" {
			transport.JSON(w, 400, transport.Error{Code: "invalid_audio_processing", Message: "audio_processing must be none or gentle"})
			return
		}
		if tts == nil {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "TTS worker is unavailable"})
			return
		}
		// Older supported TTS images treat the omitted field as plain text and
		// reject unknown fields. Forward only the non-default SSML selector.
		forwardedInputFormat := inputFormat
		if inputFormat == "text" {
			forwardedInputFormat = ""
		}
		forwardedAudioProcessing := request.AudioProcessing
		if forwardedAudioProcessing == "none" {
			forwardedAudioProcessing = ""
		}
		encoded, err := json.Marshal(struct {
			Text            string `json:"text"`
			Voice           string `json:"voice,omitempty"`
			Language        string `json:"language"`
			Mode            string `json:"mode"`
			InputFormat     string `json:"input_format,omitempty"`
			AudioProcessing string `json:"audio_processing,omitempty"`
		}{request.Text, request.Voice, request.Language, request.Mode, forwardedInputFormat, forwardedAudioProcessing})
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
		if (r.URL.Path == "/v1/stt/transcriptions" || r.URL.Path == "/v1/tts/speech" || r.URL.Path == "/v1/text/transformations") && r.ContentLength > requestBodyLimit(r.URL.Path, maxBytes) {
			transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
			return
		}
		mux.ServeHTTP(w, r)
	})
}

func validBearer(header, token string) bool {
	return transport.ValidBearer(header, token)
}
