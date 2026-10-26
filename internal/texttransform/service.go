package texttransform

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime"
	"net"
	"net/http"
	"sort"
	"strings"
	"sync/atomic"
	"time"
	"unicode/utf8"

	"speech-platform/internal/config"
	"speech-platform/internal/transport"
)

type Options struct {
	Mode           string  `json:"mode"`
	Format         string  `json:"format"`
	TargetLanguage string  `json:"target_language"`
	Model          *string `json:"model"`
	LocalOnly      bool    `json:"local_only"`
}
type Request struct {
	Text string `json:"text"`
	Options
}
type Response struct {
	OriginalText     string  `json:"original_text"`
	TransformedText  string  `json:"transformed_text"`
	Options          Options `json:"options"`
	Model            *string `json:"model"`
	Provider         *string `json:"provider"`
	FallbackOccurred bool    `json:"fallback_occurred"`
	Generated        bool    `json:"generated"`
}

type FailureKind string

const (
	FailureTransport       FailureKind = "transport"
	FailureUnavailable     FailureKind = "unavailable"
	FailureRejected        FailureKind = "rejected"
	FailureProtocol        FailureKind = "protocol"
	FailureInvalidResponse FailureKind = "invalid_response"
	FailureRefused         FailureKind = "refused"
)

type ProviderError struct {
	Kind     FailureKind
	Suppress bool
	Err      error
}

func (e *ProviderError) Error() string { return string(e.Kind) }
func (e *ProviderError) Unwrap() error { return e.Err }

type Generator interface {
	Generate(context.Context, config.TextProvider, config.TextModel, string, string, string, string) (string, error)
}

type Service struct {
	cfg         config.TextTransform
	promptFile  string
	prompt      atomic.Pointer[promptSnapshot]
	token       string
	creds       map[string]string
	client      *http.Client
	gen         Generator
	root        context.Context
	cancel      context.CancelFunc
	slots       chan struct{}
	stopped     atomic.Bool
	logger      *slog.Logger
	requests    atomic.Uint64
	attempts    atomic.Uint64
	failures    atomic.Uint64
	generated   atomic.Uint64
	passthrough atomic.Uint64
	fallbacks   atomic.Uint64
	overloaded  atomic.Uint64
}

func New(parent context.Context, cfg *config.TextTransform, token string, generator Generator, loggers ...*slog.Logger) (*Service, error) {
	var logger *slog.Logger
	if len(loggers) > 0 {
		logger = loggers[0]
	}
	if cfg == nil {
		if parent == nil {
			parent = context.Background()
		}
		root, cancel := context.WithCancel(parent)
		return &Service{token: token, root: root, cancel: cancel, logger: logger}, nil
	}
	var prompt *promptSnapshot
	if cfg.Enabled != nil && *cfg.Enabled {
		var err error
		prompt, err = loadPrompt(cfg.PromptFile)
		if err != nil {
			return nil, fmt.Errorf("text_transform: active prompt is invalid")
		}
		if err = validatePrompt(cfg, prompt.text); err != nil {
			return nil, err
		}
	}
	if parent == nil {
		parent = context.Background()
	}
	if generator == nil {
		generator = HTTPGenerator{}
	}
	ctx, cancel := context.WithCancel(parent)
	transport := &http.Transport{Proxy: nil, ForceAttemptHTTP2: true, MaxIdleConns: cfg.Transport.MaxIdleConnections, MaxIdleConnsPerHost: cfg.Transport.MaxIdleConnections, IdleConnTimeout: 30 * time.Second, TLSHandshakeTimeout: duration(cfg.Transport.TLSHandshakeTimeout), ResponseHeaderTimeout: duration(cfg.RequestTimeout), DialContext: (&net.Dialer{Timeout: duration(cfg.Transport.ConnectTimeout)}).DialContext}
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if _, ok := generator.(HTTPGenerator); ok {
		generator = HTTPGenerator{Client: client, MaxResponseBytes: cfg.MaxResponseBytes}
	}
	s := &Service{cfg: *cfg, promptFile: cfg.PromptFile, token: token, creds: cfg.ResolveCredentials(), client: client, gen: generator, root: ctx, cancel: cancel, slots: make(chan struct{}, 1), logger: logger}
	if prompt != nil {
		s.prompt.Store(prompt)
	}
	return s, nil
}

// ValidateConfig checks the configured prompt and framing fit without resolving secrets or making network calls.
func ValidateConfig(cfg *config.TextTransform) error {
	if cfg == nil || cfg.Enabled == nil || !*cfg.Enabled {
		return nil
	}
	prompt, err := loadPrompt(cfg.PromptFile)
	if err != nil {
		return fmt.Errorf("text_transform: active prompt is invalid")
	}
	return validatePrompt(cfg, prompt.text)
}

func validatePrompt(cfg *config.TextTransform, prompt string) error {
	for _, m := range cfg.Models {
		if m.Enabled == nil || !*m.Enabled {
			continue
		}
		options := optionsJSON("raw", "normal", "none")
		need := len([]byte(prompt)) + len([]byte(userPrompt("", options))) + 512 + m.PromptOverheadTokens + outputBudget(m)
		if need > m.ContextLimitTokens {
			return fmt.Errorf("text_transform model %q cannot fit the active prompt, framing and output reservation", m.ID)
		}
	}
	return nil
}

// ReloadPrompt replaces the active prompt only after the configured file passes validation.
func (s *Service) ReloadPrompt() error {
	if s == nil || s.stopped.Load() || s.root == nil || s.root.Err() != nil {
		return fmt.Errorf("text transformation service is unavailable")
	}
	next, err := loadPrompt(s.promptFile)
	if err != nil || validatePrompt(&s.cfg, next.text) != nil {
		return fmt.Errorf("configured prompt reload was rejected")
	}
	if s.stopped.Load() || s.root.Err() != nil {
		return fmt.Errorf("text transformation service is unavailable")
	}
	s.prompt.Store(next)
	return nil
}

// PromptSHA256 returns the fingerprint for the currently active prompt snapshot.
func (s *Service) PromptSHA256() string {
	if s == nil {
		return ""
	}
	if prompt := s.prompt.Load(); prompt != nil {
		return prompt.sha256
	}
	return ""
}

func (s *Service) MissingCredentials() []string {
	if s == nil || s.cfg.Enabled == nil || !*s.cfg.Enabled {
		return nil
	}
	providers := map[string]config.TextProvider{}
	for _, p := range s.cfg.Providers {
		providers[p.ID] = p
	}
	used := map[string]bool{}
	for _, m := range s.cfg.Models {
		p := providers[m.Provider]
		if m.Enabled != nil && *m.Enabled && (p.Locality == "local" || s.cfg.Selection.AllowCloud) {
			used[p.ID] = true
		}
	}
	var missing []string
	for id := range used {
		p := providers[id]
		if p.APIKeyEnv != "" && s.creds[id] == "" {
			missing = append(missing, id)
		}
	}
	sort.Strings(missing)
	return missing
}

func (s *Service) Metrics() string {
	if s == nil {
		return ""
	}
	return fmt.Sprintf("# HELP text_transform_requests_total Text transformation requests.\n# TYPE text_transform_requests_total counter\ntext_transform_requests_total %d\n# HELP text_transform_attempts_total Provider attempts.\n# TYPE text_transform_attempts_total counter\ntext_transform_attempts_total %d\n# HELP text_transform_failures_total Failed provider attempts.\n# TYPE text_transform_failures_total counter\ntext_transform_failures_total %d\n# HELP text_transform_generated_total Generated responses.\n# TYPE text_transform_generated_total counter\ntext_transform_generated_total %d\n# HELP text_transform_passthrough_total Exact raw passthrough responses.\n# TYPE text_transform_passthrough_total counter\ntext_transform_passthrough_total %d\n# HELP text_transform_fallbacks_total Responses that used a later provider model.\n# TYPE text_transform_fallbacks_total counter\ntext_transform_fallbacks_total %d\n# HELP text_transform_overloaded_total Requests rejected by text admission.\n# TYPE text_transform_overloaded_total counter\ntext_transform_overloaded_total %d\n", s.requests.Load(), s.attempts.Load(), s.failures.Load(), s.generated.Load(), s.passthrough.Load(), s.fallbacks.Load(), s.overloaded.Load())
}

// Warmup prepares the first enabled local Ollama model without invoking transformation.
func (s *Service) Warmup(ctx context.Context) (string, string) {
	if s == nil || s.stopped.Load() || s.root == nil || s.root.Err() != nil || s.cfg.Enabled == nil || !*s.cfg.Enabled {
		return "unavailable", "not_configured"
	}
	providers := make(map[string]config.TextProvider, len(s.cfg.Providers))
	for _, provider := range s.cfg.Providers {
		providers[provider.ID] = provider
	}
	for _, model := range s.cfg.Models {
		provider := providers[model.Provider]
		if model.Enabled == nil || !*model.Enabled || provider.Locality != "local" || provider.Type != "ollama" {
			continue
		}
		return s.warmOllama(ctx, provider, model)
	}
	return "unavailable", "no_eligible_local_model"
}

func (s *Service) warmOllama(ctx context.Context, provider config.TextProvider, model config.TextModel) (string, string) {
	if provider.APIKeyEnv != "" && s.creds[provider.ID] == "" {
		return "unavailable", "provider_unavailable"
	}
	requestCtx, cancel := context.WithTimeout(ctx, duration(provider.Timeout))
	defer cancel()
	keepAlive := s.cfg.WarmupKeepAlive
	if keepAlive == "" {
		keepAlive = "60s"
	}
	payload, err := json.Marshal(struct {
		Model     string `json:"model"`
		Stream    bool   `json:"stream"`
		Think     bool   `json:"think"`
		KeepAlive string `json:"keep_alive"`
	}{model.Model, false, false, keepAlive})
	if err != nil {
		return "unavailable", "provider_unavailable"
	}
	request, err := http.NewRequestWithContext(requestCtx, http.MethodPost, provider.Endpoint, bytes.NewReader(payload))
	if err != nil {
		return "unavailable", "provider_unavailable"
	}
	request.Header.Set("Content-Type", "application/json")
	if credential := s.creds[provider.ID]; credential != "" {
		request.Header.Set("Authorization", "Bearer "+credential)
	}
	response, err := s.client.Do(request)
	if err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) || errors.Is(requestCtx.Err(), context.DeadlineExceeded) {
			return "timed_out", "deadline_exceeded"
		}
		return "unavailable", "provider_unavailable"
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, int64(s.cfg.MaxResponseBytes)+1))
	if err != nil || len(body) > s.cfg.MaxResponseBytes {
		return "unavailable", "invalid_provider_response"
	}
	if response.StatusCode == http.StatusTooManyRequests {
		return "overloaded", "provider_busy"
	}
	if response.StatusCode == http.StatusRequestTimeout || response.StatusCode == http.StatusGatewayTimeout {
		return "timed_out", "deadline_exceeded"
	}
	if response.StatusCode == http.StatusServiceUnavailable || response.StatusCode >= 500 {
		return "resource_unavailable", "provider_unavailable"
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return "unavailable", "provider_rejected"
	}
	var result struct {
		Done  *bool  `json:"done"`
		Error string `json:"error"`
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	if err := decoder.Decode(&result); err != nil {
		return "unavailable", "invalid_provider_response"
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || result.Done == nil || !*result.Done {
		return "unavailable", "invalid_provider_response"
	}
	if result.Error != "" {
		return "resource_unavailable", "provider_unavailable"
	}
	return "ready", ""
}

func duration(v string) time.Duration { d, _ := time.ParseDuration(v); return d }
func (s *Service) Close() {
	if s == nil {
		return
	}
	s.stopped.Store(true)
	if s.cancel != nil {
		s.cancel()
	}
	if s.client != nil {
		s.client.CloseIdleConnections()
	}
}

func (s *Service) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	callerContext := r.Context()
	if s != nil {
		s.requests.Add(1)
	}
	if s.token != "" && !transport.ValidBearer(r.Header.Get("Authorization"), s.token) {
		writeErr(w, 401, "unauthorized")
		return
	}
	if s.cfg.Enabled != nil && *s.cfg.Enabled {
		deadlineCtx, deadlineCancel := context.WithTimeout(r.Context(), duration(s.cfg.RequestTimeout))
		stopRoot := context.AfterFunc(s.root, deadlineCancel)
		defer func() { stopRoot(); deadlineCancel() }()
		r = r.WithContext(deadlineCtx)
	}
	if r.Method != http.MethodPost {
		writeErr(w, 405, "method_not_allowed")
		return
	}
	if s.cfg.Enabled == nil || !*s.cfg.Enabled || s.stopped.Load() || s.root == nil || s.root.Err() != nil {
		writeErr(w, 503, "text_transform_unavailable")
		return
	}
	prompt := s.prompt.Load()
	if prompt == nil {
		writeErr(w, 503, "text_transform_unavailable")
		return
	}
	w.Header().Set("X-Speech-Prompt-SHA256", prompt.sha256)
	mediaType, _, mediaErr := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if mediaErr != nil || mediaType != "application/json" {
		writeErr(w, 415, "unsupported_media_type")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, int64(s.cfg.MaxRequestBytes))
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		var tooLarge *http.MaxBytesError
		if s.stopped.Load() || s.root.Err() != nil {
			writeErr(w, 503, "text_transform_unavailable")
		} else if errors.As(err, &tooLarge) {
			writeErr(w, 413, "request_too_large")
		} else if callerContext.Err() != nil {
			return
		} else if errors.Is(r.Context().Err(), context.DeadlineExceeded) {
			writeErr(w, 504, "deadline_exceeded")
			return
		} else {
			writeErr(w, 400, "invalid_request")
		}
		return
	}
	if !validJSON(raw) {
		writeErr(w, 400, "invalid_request")
		return
	}
	var rawFields map[string]json.RawMessage
	if json.Unmarshal(raw, &rawFields) != nil || rawFields == nil {
		writeErr(w, 400, "invalid_request")
		return
	}
	for _, key := range []string{"mode", "format", "target_language", "model", "local_only"} {
		if v, ok := rawFields[key]; ok && strings.TrimSpace(string(v)) == "null" {
			writeErr(w, 400, "invalid_options")
			return
		}
	}
	var req Request
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	if err = dec.Decode(&req); err != nil {
		writeErr(w, 400, "invalid_request")
		return
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		writeErr(w, 400, "invalid_request")
		return
	}
	if !utf8.ValidString(req.Text) || strings.TrimSpace(req.Text) == "" {
		writeErr(w, 400, "invalid_request")
		return
	}
	if len([]byte(req.Text)) > s.cfg.MaxInputBytes {
		writeErr(w, 413, "request_too_large")
		return
	}
	for _, key := range []string{"mode", "format", "target_language"} {
		if v, ok := rawFields[key]; ok && strings.TrimSpace(string(v)) == `""` {
			writeErr(w, 400, "invalid_options")
			return
		}
	}
	if req.Mode == "" {
		req.Mode = "raw"
	}
	if req.Format == "" {
		req.Format = "normal"
	}
	if req.TargetLanguage == "" {
		req.TargetLanguage = "none"
	}
	if !oneOf(req.Mode, "raw", "written", "polite", "diplomatic") || !oneOf(req.Format, "normal", "concise", "structured") || !oneOf(req.TargetLanguage, "none", "en", "sv", "ru") || req.Mode == "raw" && req.Format != "normal" || req.Model != nil && (*req.Model == "") {
		writeErr(w, 400, "invalid_options")
		return
	}
	providers := map[string]config.TextProvider{}
	for _, p := range s.cfg.Providers {
		providers[p.ID] = p
	}
	models := map[string]config.TextModel{}
	for _, m := range s.cfg.Models {
		models[m.ID] = m
	}
	if req.Model != nil {
		m, ok := models[*req.Model]
		if !ok {
			writeErr(w, 400, "unknown_model")
			return
		}
		if m.Enabled == nil || !*m.Enabled {
			writeErr(w, 400, "model_disabled")
			return
		}
		if providers[m.Provider].Locality == "cloud" && (!s.cfg.Selection.AllowCloud || req.LocalOnly) {
			writeErr(w, 403, "cloud_not_allowed")
			return
		}
	}
	normalized := Options{Mode: req.Mode, Format: req.Format, TargetLanguage: req.TargetLanguage, Model: req.Model, LocalOnly: req.LocalOnly}
	if req.Mode == "raw" && req.TargetLanguage == "none" {
		if s.stopped.Load() || s.root.Err() != nil {
			writeErr(w, 503, "text_transform_unavailable")
			return
		}
		if callerContext.Err() != nil {
			return
		}
		if r.Context().Err() != nil {
			if errors.Is(r.Context().Err(), context.DeadlineExceeded) {
				writeErr(w, 504, "deadline_exceeded")
			}
			return
		}
		s.passthrough.Add(1)
		writeJSON(w, 200, Response{OriginalText: req.Text, TransformedText: req.Text, Options: normalized})
		return
	}
	allowed := make([]config.TextModel, 0, len(s.cfg.Models))
	for _, m := range s.cfg.Models {
		p := providers[m.Provider]
		if m.Enabled != nil && *m.Enabled && (p.Locality == "local" || s.cfg.Selection.AllowCloud && !req.LocalOnly) {
			allowed = append(allowed, m)
		}
	}
	if req.Model != nil {
		allowed = []config.TextModel{models[*req.Model]}
	} else {
		allowed = order(allowed, providers, s.cfg.Selection.Policy)
	}
	if len(allowed) == 0 {
		writeErr(w, 503, "no_eligible_model")
		return
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		w.Header().Set("Retry-After", "2")
		s.overloaded.Add(1)
		writeErr(w, 429, "overloaded")
		return
	}
	ctx := r.Context()
	if s.stopped.Load() || s.root.Err() != nil {
		writeErr(w, 503, "text_transform_unavailable")
		return
	}
	var invoked, invalid, rejected, protocol, priorFailure bool
	attemptIndex := 0
	suppressed := map[string]bool{}
	totalBudget := -1
	for _, m := range allowed {
		if ctx.Err() != nil || s.stopped.Load() || s.root.Err() != nil {
			break
		}
		p := providers[m.Provider]
		if suppressed[p.ID] {
			continue
		}
		need := len([]byte(prompt.text)) + len([]byte(userPrompt(req.Text, optionsJSON(req.Mode, req.Format, req.TargetLanguage)))) + 512 + m.PromptOverheadTokens
		if budget := outputBudget(m); need+budget > m.ContextLimitTokens {
			if req.Model != nil {
				writeErr(w, 413, "context_limit_exceeded")
				return
			}
			continue
		}
		if totalBudget < 0 {
			totalBudget = need + outputBudget(m)
		}
		key := s.creds[p.ID]
		if p.APIKeyEnv != "" && key == "" {
			suppressed[p.ID] = true
			continue
		}
		invoked = true
		attemptIndex++
		s.attempts.Add(1)
		attemptStart := time.Now()
		if s.logger != nil {
			attrs := []any{"provider", p.ID, "model", m.ID, "attempt", attemptIndex}
			if requestID := transport.RequestID(ctx); requestID != "" {
				attrs = append(attrs, "request_id", requestID)
			}
			s.logger.Info("text provider attempt started", attrs...)
		}
		attemptCtx, attemptCancel := context.WithTimeout(ctx, duration(p.Timeout))
		out, e := s.gen.Generate(attemptCtx, p, m, s.creds[p.ID], prompt.text, req.Text, optionsJSON(req.Mode, req.Format, req.TargetLanguage))
		attemptCancel()
		if e == nil {
			if !utf8.ValidString(out) || strings.TrimSpace(out) == "" || len([]rune(out)) > s.cfg.MaxOutputCharacters {
				e = &ProviderError{Kind: FailureInvalidResponse}
			} else {
				if ctx.Err() != nil || s.root.Err() != nil || s.stopped.Load() {
					break
				}
				mid, pid := m.ID, p.ID
				s.generated.Add(1)
				if priorFailure {
					s.fallbacks.Add(1)
				}
				if s.logger != nil {
					attrs := []any{"provider", p.ID, "model", m.ID, "attempt", attemptIndex, "fallback_occurred", priorFailure, "elapsed_ms", time.Since(attemptStart).Milliseconds()}
					if requestID := transport.RequestID(ctx); requestID != "" {
						attrs = append(attrs, "request_id", requestID)
					}
					s.logger.Info("text transformation completed", attrs...)
				}
				writeJSON(w, 200, Response{OriginalText: req.Text, TransformedText: out, Options: normalized, Model: &mid, Provider: &pid, FallbackOccurred: priorFailure, Generated: true})
				return
			}
		}
		priorFailure = true
		s.failures.Add(1)
		var pe *ProviderError
		if errors.As(e, &pe) {
			if s.logger != nil {
				attrs := []any{"provider", p.ID, "model", m.ID, "attempt", attemptIndex, "category", string(pe.Kind), "suppressed", pe.Suppress, "elapsed_ms", time.Since(attemptStart).Milliseconds()}
				if requestID := transport.RequestID(ctx); requestID != "" {
					attrs = append(attrs, "request_id", requestID)
				}
				s.logger.Warn("text provider attempt failed", attrs...)
			}
			if pe.Suppress {
				suppressed[p.ID] = true
			}
			switch pe.Kind {
			case FailureInvalidResponse:
				invalid = true
			case FailureRejected:
				rejected = true
			case FailureProtocol:
				protocol = true
			case FailureRefused:
				writeErr(w, 422, "transformation_refused")
				return
			}
		}
	}
	if s.stopped.Load() || s.root.Err() != nil {
		writeErr(w, 503, "text_transform_unavailable")
		return
	}
	if callerContext.Err() != nil {
		return
	}
	if ctx.Err() != nil {
		writeErr(w, 504, "deadline_exceeded")
		return
	}
	if !invoked {
		if totalBudget >= 0 {
			writeErr(w, 503, "text_transform_unavailable")
		} else {
			writeErr(w, 413, "context_limit_exceeded")
		}
		return
	}
	if invalid {
		writeErr(w, 502, "invalid_provider_response")
	} else if rejected {
		writeErr(w, 502, "provider_request_rejected")
	} else if protocol {
		writeErr(w, 502, "provider_protocol_error")
	} else {
		writeErr(w, 503, "text_transform_failed")
	}
}

func outputBudget(m config.TextModel) int {
	if p := m.Parameters.Ollama; p != nil {
		return p.NumPredict
	}
	if p := m.Parameters.OpenAI; p != nil {
		if p.MaxCompletionTokens != nil {
			return *p.MaxCompletionTokens
		}
		if p.MaxTokens != nil {
			return *p.MaxTokens
		}
	}
	return 0
}
func order(in []config.TextModel, ps map[string]config.TextProvider, policy string) []config.TextModel {
	if policy == "ordered" {
		return in
	}
	out := make([]config.TextModel, 0, len(in))
	first := "local"
	if policy == "cloud_first" {
		first = "cloud"
	}
	for _, m := range in {
		if ps[m.Provider].Locality == first {
			out = append(out, m)
		}
	}
	for _, m := range in {
		if ps[m.Provider].Locality != first {
			out = append(out, m)
		}
	}
	return out
}
func optionsJSON(mode, format, lang string) string {
	b, _ := json.Marshal(map[string]string{"mode": mode, "format": format, "target_language": lang})
	return string(b)
}
func oneOf(v string, choices ...string) bool {
	for _, c := range choices {
		if v == c {
			return true
		}
	}
	return false
}
func writeErr(w http.ResponseWriter, code int, kind string) {
	msg := map[string]string{"unauthorized": "valid bearer token required", "unsupported_media_type": "application/json is required", "text_transform_unavailable": "text transformation is unavailable", "no_eligible_model": "no eligible model is configured", "invalid_request": "request contains invalid or unsupported fields", "invalid_options": "request options are invalid", "request_too_large": "request size limit exceeded", "context_limit_exceeded": "input exceeds configured context limits", "unknown_model": "model is not configured", "model_disabled": "model is disabled", "cloud_not_allowed": "cloud inference is not permitted", "overloaded": "text transformation capacity is full", "transformation_refused": "provider refused the request", "deadline_exceeded": "text transformation deadline exceeded", "provider_request_rejected": "provider rejected the request", "provider_protocol_error": "provider protocol failed", "invalid_provider_response": "provider returned an invalid response", "text_transform_failed": "text transformation failed"}[kind]
	if msg == "" {
		msg = "request failed"
	}
	transport.JSON(w, code, transport.Error{Code: kind, Message: msg})
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func validJSON(raw []byte) bool {
	if !utf8.Valid(raw) || hasLoneSurrogate(raw) {
		return false
	}
	d := json.NewDecoder(strings.NewReader(string(raw)))
	if !walkJSONValue(d) {
		return false
	}
	_, err := d.Token()
	return err == io.EOF
}

func walkJSONValue(d *json.Decoder) bool {
	t, err := d.Token()
	if err != nil {
		return false
	}
	delim, ok := t.(json.Delim)
	if !ok {
		return true
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			k, err := d.Token()
			if err != nil {
				return false
			}
			key, ok := k.(string)
			if !ok || seen[key] {
				return false
			}
			seen[key] = true
			if !walkJSONValue(d) {
				return false
			}
		}
		end, err := d.Token()
		return err == nil && end == json.Delim('}')
	case '[':
		for d.More() {
			if !walkJSONValue(d) {
				return false
			}
		}
		end, err := d.Token()
		return err == nil && end == json.Delim(']')
	default:
		return false
	}
}

func hasLoneSurrogate(raw []byte) bool {
	for i := 0; i < len(raw); i++ {
		if raw[i] != '\\' {
			continue
		}
		i++
		if i >= len(raw) {
			return true
		}
		if raw[i] != 'u' {
			continue
		}
		if i+4 >= len(raw) {
			return true
		}
		n := 0
		for j := 1; j <= 4; j++ {
			c := raw[i+j]
			n <<= 4
			switch {
			case c >= '0' && c <= '9':
				n += int(c - '0')
			case c >= 'a' && c <= 'f':
				n += int(c-'a') + 10
			case c >= 'A' && c <= 'F':
				n += int(c-'A') + 10
			default:
				return true
			}
		}
		i += 4
		if n >= 0xD800 && n <= 0xDBFF {
			if i+6 >= len(raw) || raw[i+1] != '\\' || raw[i+2] != 'u' {
				return true
			}
			low := 0
			for j := 3; j <= 6; j++ {
				c := raw[i+j]
				low <<= 4
				switch {
				case c >= '0' && c <= '9':
					low += int(c - '0')
				case c >= 'a' && c <= 'f':
					low += int(c-'a') + 10
				case c >= 'A' && c <= 'F':
					low += int(c-'A') + 10
				default:
					return true
				}
			}
			if low < 0xDC00 || low > 0xDFFF {
				return true
			}
			i += 6
		} else if n >= 0xDC00 && n <= 0xDFFF {
			return true
		}
	}
	return false
}
