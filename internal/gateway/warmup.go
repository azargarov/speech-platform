package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"sync"
	"time"

	"speech-platform/internal/transport"
)

const warmupBodyLimit int64 = 4 * 1024

type warmupRequest struct {
	Operations []string `json:"operations"`
}

type warmupResult struct {
	Operation string `json:"operation"`
	Status    string `json:"status"`
	Code      string `json:"code,omitempty"`
}

type warmupResponse struct {
	Results  []warmupResult `json:"results"`
	Complete bool           `json:"complete"`
}

type warmupFlight struct {
	done    chan struct{}
	result  warmupResult
	started bool
}

type warmupCoordinator struct {
	mu      sync.Mutex
	flights map[string]*warmupFlight
	serial  chan struct{}
}

func newWarmupCoordinator() *warmupCoordinator {
	return &warmupCoordinator{flights: make(map[string]*warmupFlight), serial: make(chan struct{}, 1)}
}

func (c *warmupCoordinator) run(ctx, root context.Context, maxAttempt time.Duration, operation string, fn func(context.Context) warmupResult) warmupResult {
	if root == nil {
		root = context.Background()
	}
	if maxAttempt <= 0 {
		maxAttempt = 180 * time.Second
	}
	c.mu.Lock()
	if current := c.flights[operation]; current != nil {
		c.mu.Unlock()
		return c.wait(ctx, current, operation)
	}
	flight := &warmupFlight{done: make(chan struct{})}
	c.flights[operation] = flight
	c.mu.Unlock()

	// The attempt belongs to the coordinator, not to whichever HTTP request
	// happened to create it. Individual callers only cancel their own wait.
	attemptCtx, cancel := context.WithTimeout(root, maxAttempt)
	go c.execute(attemptCtx, cancel, operation, flight, fn)
	return c.wait(ctx, flight, operation)
}

func (c *warmupCoordinator) wait(ctx context.Context, flight *warmupFlight, operation string) warmupResult {
	select {
	case <-flight.done:
		return flight.result
	case <-ctx.Done():
		select {
		case <-flight.done:
			return flight.result
		default:
		}
		c.mu.Lock()
		started := flight.started
		c.mu.Unlock()
		if !started {
			return warmupResult{Operation: operation, Status: "not_attempted", Code: "deadline_exceeded"}
		}
		return warmupResult{Operation: operation, Status: "warming", Code: "still_in_progress"}
	}
}

func (c *warmupCoordinator) execute(ctx context.Context, cancel context.CancelFunc, operation string, flight *warmupFlight, fn func(context.Context) warmupResult) {
	defer cancel()
	result := warmupResult{Operation: operation, Status: "not_attempted", Code: "deadline_exceeded"}
	select {
	case c.serial <- struct{}{}:
		if ctx.Err() == nil {
			c.mu.Lock()
			flight.started = true
			c.mu.Unlock()
			result = fn(ctx)
		}
		<-c.serial
	case <-ctx.Done():
	}
	c.mu.Lock()
	flight.result = result
	delete(c.flights, operation)
	close(flight.done)
	c.mu.Unlock()
}

func serveWarmup(w http.ResponseWriter, r *http.Request, token string, coordinator *warmupCoordinator, slots chan struct{}, stt *STTProxy, tts *TTSProxy, text http.Handler, timeout time.Duration, root context.Context) {
	if r.Method != http.MethodPost {
		transport.JSON(w, http.StatusMethodNotAllowed, transport.Error{Code: "method_not_allowed", Message: "POST is required"})
		return
	}
	if token != "" && !validBearer(r.Header.Get("Authorization"), token) {
		transport.JSON(w, http.StatusUnauthorized, transport.Error{Code: "unauthorized", Message: "valid bearer token required"})
		return
	}
	if root.Err() != nil {
		transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "gateway_stopping", Message: "Gateway is stopping"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	stopRoot := context.AfterFunc(root, cancel)
	defer stopRoot()
	defer cancel()
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		transport.JSON(w, http.StatusUnsupportedMediaType, transport.Error{Code: "unsupported_media_type", Message: "application/json is required"})
		return
	}
	if r.ContentLength > warmupBodyLimit {
		transport.JSON(w, http.StatusRequestEntityTooLarge, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, warmupBodyLimit)
	requestBody := r.Body
	stopBody := context.AfterFunc(ctx, func() { _ = requestBody.Close() })
	defer stopBody()
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			transport.JSON(w, http.StatusRequestEntityTooLarge, transport.Error{Code: "request_too_large", Message: "request size limit exceeded"})
		} else if root.Err() != nil {
			transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "gateway_stopping", Message: "Gateway is stopping"})
		} else if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			transport.JSON(w, http.StatusRequestTimeout, transport.Error{Code: "deadline_exceeded", Message: "warmup request deadline exceeded"})
		} else if r.Context().Err() != nil {
			return
		} else {
			transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request", Message: "request body could not be read"})
		}
		return
	}
	var request warmupRequest
	if !jsonHasUniqueKeys(raw) {
		transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request", Message: "request contains invalid or duplicate JSON fields"})
		return
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request", Message: "request contains invalid or unsupported fields"})
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || len(request.Operations) < 1 || len(request.Operations) > 3 {
		transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request", Message: "operations must contain one to three unique operations"})
		return
	}
	seen := make(map[string]bool, len(request.Operations))
	for _, operation := range request.Operations {
		if operation != "stt" && operation != "tts" && operation != "text_transform" || seen[operation] {
			transport.JSON(w, http.StatusBadRequest, transport.Error{Code: "invalid_request", Message: "operations must contain one to three unique supported operations"})
			return
		}
		seen[operation] = true
	}
	canAttempt := false
	for _, operation := range request.Operations {
		switch operation {
		case "stt":
			canAttempt = canAttempt || stt != nil && stt.Client != nil
		case "tts":
			canAttempt = canAttempt || tts != nil && tts.Client != nil
		case "text_transform":
			_, ok := text.(interface {
				Warmup(context.Context) (string, string)
			})
			canAttempt = canAttempt || ok
		}
	}
	if !canAttempt {
		transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "warmup_unavailable", Message: "no requested warmup operation is available"})
		return
	}
	select {
	case slots <- struct{}{}:
		defer func() { <-slots }()
	default:
		results := make([]warmupResult, 0, len(request.Operations))
		for _, operation := range request.Operations {
			results = append(results, warmupResult{Operation: operation, Status: "overloaded", Code: "gateway_busy"})
		}
		transport.JSON(w, http.StatusOK, warmupResponse{Results: results, Complete: false})
		return
	}

	results := make([]warmupResult, 0, len(request.Operations))
	for _, operation := range request.Operations {
		if ctx.Err() != nil {
			results = append(results, warmupResult{Operation: operation, Status: "not_attempted", Code: "deadline_exceeded"})
			continue
		}
		result := coordinator.run(ctx, root, timeout, operation, func(opCtx context.Context) warmupResult {
			switch operation {
			case "stt":
				return stt.warmup(opCtx)
			case "tts":
				return tts.warmup(opCtx)
			default:
				warmer, ok := text.(interface {
					Warmup(context.Context) (string, string)
				})
				if !ok {
					return warmupResult{Operation: operation, Status: "unavailable", Code: "not_configured"}
				}
				status, code := warmer.Warmup(opCtx)
				return warmupResult{Operation: operation, Status: status, Code: code}
			}
		})
		results = append(results, result)
	}
	complete := true
	for _, result := range results {
		if result.Status != "ready" {
			complete = false
		}
	}
	if root.Err() != nil {
		transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "gateway_stopping", Message: "Gateway is stopping"})
		return
	}
	if r.Context().Err() != nil {
		return
	}
	transport.JSON(w, http.StatusOK, warmupResponse{Results: results, Complete: complete})
}

func jsonHasUniqueKeys(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if !consumeJSONValue(decoder) {
		return false
	}
	_, err := decoder.Token()
	return err == io.EOF
}

func consumeJSONValue(decoder *json.Decoder) bool {
	token, err := decoder.Token()
	if err != nil {
		return false
	}
	delim, ok := token.(json.Delim)
	if !ok {
		return true
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			keyToken, err := decoder.Token()
			key, ok := keyToken.(string)
			if err != nil || !ok || seen[key] || !consumeJSONValue(decoder) {
				return false
			}
			seen[key] = true
		}
		end, err := decoder.Token()
		return err == nil && end == json.Delim('}')
	case '[':
		for decoder.More() {
			if !consumeJSONValue(decoder) {
				return false
			}
		}
		end, err := decoder.Token()
		return err == nil && end == json.Delim(']')
	default:
		return false
	}
}

func (p *STTProxy) warmup(ctx context.Context) warmupResult {
	if p == nil {
		return warmupResult{Operation: "stt", Status: "unavailable", Code: "worker_unavailable"}
	}
	return workerWarmup(ctx, p.BaseURL, p.Token, p.Client, p.Timeout, "stt")
}

func (p *TTSProxy) warmup(ctx context.Context) warmupResult {
	if p == nil {
		return warmupResult{Operation: "tts", Status: "unavailable", Code: "worker_unavailable"}
	}
	return workerWarmup(ctx, p.BaseURL, p.Token, p.Client, p.Timeout, "tts")
}

func workerWarmup(ctx context.Context, baseURL, token string, client *http.Client, timeout time.Duration, operation string) warmupResult {
	if client == nil || baseURL == "" {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "worker_unavailable"}
	}
	requestCtx := ctx
	cancel := func() {}
	if timeout > 0 {
		requestCtx, cancel = context.WithTimeout(ctx, timeout)
	}
	defer cancel()
	request, err := http.NewRequestWithContext(requestCtx, http.MethodPost, baseURL+"/internal/v1/warmup", http.NoBody)
	if err != nil {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "worker_unavailable"}
	}
	request.Header.Set("Content-Length", "0")
	if operation == "stt" {
		request.Header.Set("X-Request-Timeout-Ms", durationHeader(requestCtx, timeout))
	}
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := client.Do(request)
	if err != nil {
		if errors.Is(requestCtx.Err(), context.DeadlineExceeded) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return warmupResult{Operation: operation, Status: "timed_out", Code: "deadline_exceeded"}
		}
		return warmupResult{Operation: operation, Status: "unavailable", Code: "worker_unavailable"}
	}
	defer response.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 16*1024+1))
	if readErr != nil || len(body) > 16*1024 {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "invalid_worker_response"}
	}
	if response.StatusCode == http.StatusTooManyRequests {
		return warmupResult{Operation: operation, Status: "overloaded", Code: "worker_busy"}
	}
	if response.StatusCode == http.StatusRequestTimeout || response.StatusCode == http.StatusGatewayTimeout {
		return warmupResult{Operation: operation, Status: "timed_out", Code: "deadline_exceeded"}
	}
	if response.StatusCode == http.StatusServiceUnavailable || response.StatusCode >= 500 {
		return warmupResult{Operation: operation, Status: "resource_unavailable", Code: "worker_unavailable"}
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "worker_rejected"}
	}
	var state struct {
		ModelState      string `json:"model_state"`
		InferenceActive *bool  `json:"inference_active"`
	}
	if json.Unmarshal(body, &state) != nil {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "invalid_worker_response"}
	}
	expectedState := "ready"
	if operation == "tts" {
		expectedState = "loaded"
		if state.InferenceActive == nil || *state.InferenceActive {
			return warmupResult{Operation: operation, Status: "unavailable", Code: "invalid_worker_response"}
		}
	}
	if state.ModelState != expectedState {
		return warmupResult{Operation: operation, Status: "unavailable", Code: "invalid_worker_response"}
	}
	return warmupResult{Operation: operation, Status: "ready"}
}

func durationHeader(ctx context.Context, maximum time.Duration) string {
	remaining := maximum
	if deadline, ok := ctx.Deadline(); ok {
		if until := time.Until(deadline); remaining <= 0 || until < remaining {
			remaining = until
		}
	}
	if remaining < time.Millisecond {
		remaining = time.Millisecond
	}
	return fmt.Sprint(remaining.Milliseconds())
}
