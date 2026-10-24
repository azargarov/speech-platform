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
	maxTTSRequestBytes      int64 = 64 * 1024
	maxTextRequestBytes     int64 = 64 * 1024
	maxSSMLDocumentBytes          = 48 * 1024
	maxTTSResponseBytes           = 64 * 1024 * 1024
	maxSTTResponseBytes     int64 = 2 * 1024 * 1024
	sttRequestQueueCapacity       = 3 // one active request plus three FIFO waiters
	ttsRequestQueueCapacity       = 1 // one active request plus one FIFO waiter
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
	return &TTSProxy{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, Timeout: timeout, Client: &http.Client{Timeout: timeout}}
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
	return &STTProxy{BaseURL: strings.TrimRight(baseURL, "/"), Token: token, Timeout: timeout, Client: &http.Client{Timeout: timeout}}
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
	sttAdmission := newSTTAdmission(sttRequestQueueCapacity)
	ttsAdmission := newSpeechAdmission(ttsRequestQueueCapacity)
	if warmupRoot.Done() != nil {
		context.AfterFunc(warmupRoot, func() {
			sttAdmission.shutdown()
			ttsAdmission.shutdown()
		})
	}
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
		bodyLimit := requestBodyLimit(r.URL.Path, maxBytes)
		if r.ContentLength > bodyLimit {
			transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, bodyLimit)
		timeout := time.Duration(0)
		if stt != nil {
			timeout = stt.Timeout
		}
		ctx, finish, beginDelivery := speechContext(w, r, timeout)
		defer finish()
		if speechStopped(w, ctx) {
			return
		}
		admissionLease, full, admissionErr := sttAdmission.acquire(ctx, localWhisperProvider)
		if admissionErr != nil {
			writeAdmissionError(w, ctx, admissionErr)
			return
		}
		if full {
			if speechStopped(w, ctx) {
				return
			}
			w.Header().Set("Retry-After", "2")
			transport.JSON(w, 429, transport.Error{Code: "overloaded", Message: "Gateway request capacity is full"})
			return
		}
		defer admissionLease.Release()
		if speechStopped(w, ctx) {
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			if speechStopped(w, ctx) {
				return
			}
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
				return
			}
			transport.JSON(w, 400, transport.Error{Code: "invalid_request_body", Message: "request body could not be read"})
			return
		}
		if speechStopped(w, ctx) {
			return
		}
		if stt == nil {
			transport.JSON(w, 503, transport.Error{Code: "not_ready", Message: "STT worker is unavailable"})
			return
		}
		if speechStopped(w, ctx) {
			return
		}
		budget := speechBudget(ctx)
		if budget == "" {
			transport.JSON(w, 504, transport.Error{Code: "deadline_exceeded", Message: "speech request deadline exceeded"})
			return
		}
		upstream, err := http.NewRequestWithContext(ctx, http.MethodPost, stt.BaseURL+"/internal/v1/transcriptions", bytes.NewReader(body))
		if err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request could not be forwarded"})
			return
		}
		upstream.Header.Set("Content-Type", r.Header.Get("Content-Type"))
		upstream.Header.Set("X-Request-Timeout-Ms", budget)
		if speechStopped(w, ctx) {
			return
		}
		response, err := stt.Client.Do(upstream)
		if err != nil {
			speechWorkerFailure(w, ctx, err)
			return
		}
		defer response.Body.Close()
		responseBody, err := io.ReadAll(io.LimitReader(response.Body, maxSTTResponseBytes+1))
		if speechStopped(w, ctx) {
			return
		}
		if speechTimedOut(ctx, err) {
			speechWorkerFailure(w, ctx, err)
			return
		}
		if err != nil || int64(len(responseBody)) > maxSTTResponseBytes {
			transport.JSON(w, 502, transport.Error{Code: "invalid_worker_response", Message: "STT worker returned an invalid response"})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(response.StatusCode)
		beginDelivery()
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
		bodyLimit := requestBodyLimit(r.URL.Path, maxBytes)
		if r.ContentLength > bodyLimit {
			transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, bodyLimit)
		timeout := time.Duration(0)
		if tts != nil {
			timeout = tts.Timeout
		}
		ctx, finish, beginDelivery := speechContext(w, r, timeout)
		defer finish()
		if speechStopped(w, ctx) {
			return
		}
		admissionLease, full, admissionErr := ttsAdmission.acquire(ctx, defaultSpeechProvider)
		if admissionErr != nil {
			writeAdmissionError(w, ctx, admissionErr)
			return
		}
		if full {
			if speechStopped(w, ctx) {
				return
			}
			w.Header().Set("Retry-After", "2")
			transport.JSON(w, 429, transport.Error{Code: "overloaded", Message: "Gateway request capacity is full"})
			return
		}
		defer admissionLease.Release()
		if speechStopped(w, ctx) {
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			if speechStopped(w, ctx) {
				return
			}
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				transport.JSON(w, 413, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
			} else {
				transport.JSON(w, 400, transport.Error{Code: "invalid_request_body", Message: "request body could not be read"})
			}
			return
		}
		if speechStopped(w, ctx) {
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
		if speechStopped(w, ctx) {
			return
		}
		budget := speechBudget(ctx)
		if budget == "" {
			transport.JSON(w, 504, transport.Error{Code: "deadline_exceeded", Message: "speech request deadline exceeded"})
			return
		}
		upstream, err := http.NewRequestWithContext(ctx, http.MethodPost, tts.BaseURL+"/internal/v1/speech", bytes.NewReader(encoded))
		if err != nil {
			transport.JSON(w, 400, transport.Error{Code: "invalid_request", Message: "request could not be forwarded"})
			return
		}
		upstream.Header.Set("Content-Type", "application/json")
		upstream.Header.Set("X-Request-Timeout-Ms", budget)
		if speechStopped(w, ctx) {
			return
		}
		response, err := tts.Client.Do(upstream)
		if err != nil {
			speechWorkerFailure(w, ctx, err)
			return
		}
		defer response.Body.Close()
		responseBody, tooLarge, err := readBoundedTTSResponse(response.Body, response.ContentLength, maxTTSResponseBytes)
		if speechStopped(w, ctx) {
			return
		}
		if speechTimedOut(ctx, err) {
			speechWorkerFailure(w, ctx, err)
			return
		}
		if err != nil || tooLarge {
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
		beginDelivery()
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

func writeAdmissionError(w http.ResponseWriter, ctx context.Context, err error) {
	if speechStopped(w, ctx) {
		return
	}
	if errors.Is(err, ErrAdmissionClosed) {
		transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "not_ready", Message: "Gateway is shutting down"})
		return
	}
	transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "worker_unavailable", Message: "no eligible speech provider is available"})
}

// readBoundedTTSResponse avoids io.ReadAll growth overshooting the configured
// audio ceiling. Workers send Content-Length; unknown-length responses use one
// fixed max+1 buffer so chunked or malformed workers remain bounded too.
func readBoundedTTSResponse(body io.Reader, contentLength, maxBytes int64) ([]byte, bool, error) {
	if contentLength > maxBytes {
		return nil, true, nil
	}
	if contentLength >= 0 {
		buffer := make([]byte, int(contentLength))
		if _, err := io.ReadFull(body, buffer); err != nil {
			return nil, false, err
		}
		return buffer, false, nil
	}
	buffer := make([]byte, int(maxBytes)+1)
	n, err := io.ReadFull(body, buffer)
	if int64(n) > maxBytes {
		return nil, true, nil
	}
	if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
		return nil, false, err
	}
	return buffer[:n], false, nil
}

func validBearer(header, token string) bool {
	return transport.ValidBearer(header, token)
}
