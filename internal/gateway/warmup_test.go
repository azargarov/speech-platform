package gateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"speech-platform/internal/config"
	"speech-platform/internal/texttransform"
)

const warmupTestToken = "01234567890123456789012345678901"

func decodeWarmup(t *testing.T, recorder *httptest.ResponseRecorder) warmupResponse {
	t.Helper()
	var response warmupResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode response %q: %v", recorder.Body.String(), err)
	}
	return response
}

func postWarmup(h http.Handler, body string, token string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(http.MethodPost, "/v1/models/warmup", strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func TestPublicWarmupValidatesBeforeSideEffectsAndEnforcesAuth(t *testing.T) {
	var calls atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/internal/v1/warmup" || r.Header.Get("X-Request-Timeout-Ms") == "" {
			t.Errorf("bad warmup request: %s %#v", r.URL.Path, r.Header)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"model_state":"ready"}`))
	}))
	defer worker.Close()
	stt := NewSTTProxy(worker.URL, warmupTestToken, time.Second)
	h := HandlerWithWorkersAndText(Foundation{}, 1024, stt, nil, nil)
	if got := postWarmup(h, `{"operations":["stt"]}`, ""); got.Code != http.StatusUnauthorized || calls.Load() != 0 {
		t.Fatalf("unauthorized status=%d calls=%d", got.Code, calls.Load())
	}
	for _, body := range []string{`{`, `{"operations":["stt"],"operations":["tts"]}`, `{"operations":["stt"],"extra":true}`, `{"operations":["bad"]}`, `{"operations":[]}`, `{"operations":["stt","stt"]}`, `{"operations":["stt"]} {}`} {
		w := postWarmup(h, body, warmupTestToken)
		if w.Code != http.StatusBadRequest || calls.Load() != 0 {
			t.Fatalf("body=%s status=%d calls=%d response=%s", body, w.Code, calls.Load(), w.Body.String())
		}
	}
	oversized := postWarmup(h, `{"operations":["stt"]}`+strings.Repeat(" ", 4100), warmupTestToken)
	if oversized.Code != http.StatusRequestEntityTooLarge || calls.Load() != 0 {
		t.Fatalf("oversized status=%d calls=%d", oversized.Code, calls.Load())
	}
	chunkedRequest := httptest.NewRequest(http.MethodPost, "/v1/models/warmup", strings.NewReader(`{"operations":["stt"]}`+strings.Repeat(" ", 4100)))
	chunkedRequest.ContentLength = -1
	chunkedRequest.Header.Set("Content-Type", "application/json")
	chunkedRequest.Header.Set("Authorization", "Bearer "+warmupTestToken)
	chunkedResponse := httptest.NewRecorder()
	h.ServeHTTP(chunkedResponse, chunkedRequest)
	if chunkedResponse.Code != http.StatusRequestEntityTooLarge || calls.Load() != 0 {
		t.Fatalf("chunked status=%d calls=%d", chunkedResponse.Code, calls.Load())
	}
	valid := postWarmup(h, `{"operations":["stt"]}`, warmupTestToken)
	response := decodeWarmup(t, valid)
	if valid.Code != http.StatusOK || !response.Complete || len(response.Results) != 1 || response.Results[0].Status != "ready" || calls.Load() != 1 {
		t.Fatalf("status=%d response=%+v calls=%d", valid.Code, response, calls.Load())
	}
}

type stalledWarmupBody struct{ closed chan struct{} }

func (b *stalledWarmupBody) Read([]byte) (int, error) { <-b.closed; return 0, io.ErrClosedPipe }
func (b *stalledWarmupBody) Close() error {
	select {
	case <-b.closed:
	default:
		close(b.closed)
	}
	return nil
}

func TestPublicWarmupStalledBodyUsesTotalDeadlineBeforeSideEffects(t *testing.T) {
	var calls atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { calls.Add(1) }))
	defer worker.Close()
	stt := NewSTTProxy(worker.URL, "", time.Second)
	h := HandlerWithWarmupContext(Foundation{}, 1024, stt, nil, nil, 25*time.Millisecond, context.Background())
	request := httptest.NewRequest(http.MethodPost, "/v1/models/warmup", nil)
	request.Body = &stalledWarmupBody{closed: make(chan struct{})}
	request.ContentLength = -1
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	h.ServeHTTP(response, request)
	if response.Code != http.StatusRequestTimeout || calls.Load() != 0 {
		t.Fatalf("status=%d calls=%d body=%s", response.Code, calls.Load(), response.Body.String())
	}
}

func TestPublicWarmupPartialFailureAndTTSBusy(t *testing.T) {
	sttWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/warmup" || r.Header.Get("X-Request-Timeout-Ms") == "" {
			t.Errorf("bad STT request: %s %#v", r.URL.Path, r.Header)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"model_state":"ready"}`))
	}))
	defer sttWorker.Close()
	ttsWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/warmup" || r.Header.Get("X-Request-Timeout-Ms") != "" {
			t.Errorf("bad TTS request: %s %#v", r.URL.Path, r.Header)
		}
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer ttsWorker.Close()
	stt := NewSTTProxy(sttWorker.URL, "", time.Second)
	tts := NewTTSProxy(ttsWorker.URL, "", time.Second)
	h := HandlerWithWorkersAndText(Foundation{}, 1024, stt, tts, nil)
	w := postWarmup(h, `{"operations":["stt","tts"]}`, "")
	result := decodeWarmup(t, w)
	if w.Code != 200 || result.Complete || result.Results[0].Status != "ready" || result.Results[1].Status != "overloaded" {
		t.Fatalf("status=%d result=%+v", w.Code, result)
	}
}

func TestPublicWarmupAllUnavailableAndSanitizedWorkerFailures(t *testing.T) {
	h := HandlerWithWorkersAndText(Foundation{}, 1024, nil, nil, nil)
	response := postWarmup(h, `{"operations":["stt"]}`, "")
	if response.Code != http.StatusServiceUnavailable || strings.Contains(response.Body.String(), "worker") {
		t.Fatalf("unconfigured warmup status=%d body=%s", response.Code, response.Body.String())
	}

	for _, tc := range []struct {
		name       string
		status     int
		body       string
		wantStatus string
		wantCode   string
	}{
		{"malformed_success", http.StatusOK, `{`, "unavailable", "invalid_worker_response"},
		{"incomplete_success", http.StatusOK, `{"model_state":"loading"}`, "unavailable", "invalid_worker_response"},
		{"resource_failure", http.StatusServiceUnavailable, `secret provider diagnostic`, "resource_unavailable", "worker_unavailable"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = io.WriteString(w, tc.body)
			}))
			defer worker.Close()
			proxy := NewSTTProxy(worker.URL, "", time.Second)
			result := proxy.warmup(context.Background())
			if result.Status != tc.wantStatus || result.Code != tc.wantCode || strings.Contains(result.Code, "secret") {
				t.Fatalf("result=%+v", result)
			}
		})
	}
}

func TestPublicWarmupResourceUnavailablePreservesReadyOperation(t *testing.T) {
	sttWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"model_state":"ready"}`)
	}))
	defer sttWorker.Close()
	ttsWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, `secret resource diagnostic`)
	}))
	defer ttsWorker.Close()
	h := HandlerWithWorkersAndText(
		Foundation{}, 1024,
		NewSTTProxy(sttWorker.URL, "", time.Second),
		NewTTSProxy(ttsWorker.URL, "", time.Second),
		nil,
	)
	response := postWarmup(h, `{"operations":["stt","tts"]}`, "")
	result := decodeWarmup(t, response)
	if response.Code != http.StatusOK || result.Complete || len(result.Results) != 2 || result.Results[0].Status != "ready" || result.Results[1].Status != "resource_unavailable" || strings.Contains(response.Body.String(), "secret") {
		t.Fatalf("status=%d result=%+v body=%s", response.Code, result, response.Body.String())
	}
}

func TestTTSWarmupSuccessUnavailableAndTimeout(t *testing.T) {
	success := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/warmup" || r.ContentLength != 0 || r.Header.Get("X-Request-Timeout-Ms") != "" {
			t.Errorf("unexpected TTS warmup request: %#v", r)
		}
		_, _ = w.Write([]byte(`{"model_state":"loaded","inference_active":false}`))
	}))
	tts := NewTTSProxy(success.URL, "", time.Second)
	if result := tts.warmup(context.Background()); result.Status != "ready" {
		t.Fatalf("successful TTS warmup=%+v", result)
	}
	success.Close()
	for _, body := range []string{
		`{"model_state":"ready","inference_active":false}`,
		`{"model_state":"loaded"}`,
		`{"model_state":"loaded","inference_active":true}`,
	} {
		worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = io.WriteString(w, body)
		}))
		proxy := NewTTSProxy(worker.URL, "", time.Second)
		if result := proxy.warmup(context.Background()); result.Status != "unavailable" || result.Code != "invalid_worker_response" {
			t.Errorf("invalid TTS response %s: %+v", body, result)
		}
		worker.Close()
	}
	if result := tts.warmup(context.Background()); result.Status != "unavailable" {
		t.Fatalf("unavailable TTS warmup=%+v", result)
	}

	blocked := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) { <-r.Context().Done() }))
	defer blocked.Close()
	short := NewTTSProxy(blocked.URL, "", 20*time.Millisecond)
	if result := short.warmup(context.Background()); result.Status != "timed_out" {
		t.Fatalf("timed out TTS warmup=%+v", result)
	}
}

func TestPublicTextTransformWarmupDoesNotExposeOrAcceptUserContent(t *testing.T) {
	var calls atomic.Int32
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Errorf("decode provider warmup: %v", err)
		}
		if _, exists := payload["prompt"]; exists {
			t.Errorf("warmup sent prompt: %#v", payload)
		}
		if _, exists := payload["system"]; exists {
			t.Errorf("warmup sent system text: %#v", payload)
		}
		_, _ = w.Write([]byte(`{"response":"synthetic generated content","done":true}`))
	}))
	defer provider.Close()
	cfg, err := config.Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	cfg.TextTransform.Providers[0].Endpoint = provider.URL + "/api/generate"
	service, err := texttransform.New(context.Background(), cfg.TextTransform, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	h := HandlerWithWorkersAndText(Foundation{}, 1024, nil, nil, service)
	response := postWarmup(h, `{"operations":["text_transform"]}`, "")
	result := decodeWarmup(t, response)
	if response.Code != http.StatusOK || !result.Complete || calls.Load() != 1 {
		t.Fatalf("status=%d result=%+v calls=%d", response.Code, result, calls.Load())
	}
	if strings.Contains(response.Body.String(), "synthetic generated content") || strings.Contains(response.Body.String(), "local-qwen") {
		t.Fatalf("public warmup leaked provider output or model alias: %s", response.Body.String())
	}
}

func TestWarmupCoordinatorCoalescesAndReportsStillWarming(t *testing.T) {
	coordinator := newWarmupCoordinator()
	entered := make(chan struct{})
	release := make(chan struct{})
	var calls atomic.Int32
	fn := func(context.Context) warmupResult {
		calls.Add(1)
		close(entered)
		<-release
		return warmupResult{Operation: "stt", Status: "ready"}
	}
	first := make(chan warmupResult, 1)
	go func() { first <- coordinator.run(context.Background(), context.Background(), time.Second, "stt", fn) }()
	<-entered
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	second := coordinator.run(ctx, context.Background(), time.Second, "stt", fn)
	if second.Status != "warming" || calls.Load() != 1 {
		t.Fatalf("second=%+v calls=%d", second, calls.Load())
	}
	close(release)
	if result := <-first; result.Status != "ready" {
		t.Fatalf("first=%+v", result)
	}
}

type notifyingContext struct {
	context.Context
	notified chan struct{}
	once     sync.Once
}

func (c *notifyingContext) Done() <-chan struct{} {
	c.once.Do(func() { close(c.notified) })
	return c.Context.Done()
}

func waitForWarmupWaiter(t *testing.T, ctx *notifyingContext) {
	t.Helper()
	select {
	case <-ctx.notified:
	case <-time.After(time.Second):
		t.Fatal("caller did not join the shared attempt")
	}
}

func TestWarmupInitiatorCancellationDoesNotCancelFollower(t *testing.T) {
	c := newWarmupCoordinator()
	root, stop := context.WithCancel(context.Background())
	defer stop()
	entered, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	fn := func(ctx context.Context) warmupResult {
		calls.Add(1)
		close(entered)
		select {
		case <-release:
			return warmupResult{Operation: "stt", Status: "ready"}
		case <-ctx.Done():
			return warmupResult{Operation: "stt", Status: "timed_out", Code: "deadline_exceeded"}
		}
	}
	initiatorCtx, cancelInitiator := context.WithCancel(context.Background())
	initiator := make(chan warmupResult, 1)
	go func() { initiator <- c.run(initiatorCtx, root, time.Second, "stt", fn) }()
	<-entered

	followerCtx := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
	follower := make(chan warmupResult, 1)
	go func() { follower <- c.run(followerCtx, root, time.Second, "stt", fn) }()
	waitForWarmupWaiter(t, followerCtx)
	followerCtx2 := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
	follower2 := make(chan warmupResult, 1)
	go func() { follower2 <- c.run(followerCtx2, root, time.Second, "stt", fn) }()
	waitForWarmupWaiter(t, followerCtx2)
	cancelInitiator()
	if got := <-initiator; got.Status != "warming" {
		t.Fatalf("cancelled initiator result=%+v", got)
	}
	close(release)
	if got := <-follower; got.Status != "ready" || calls.Load() != 1 {
		t.Fatalf("follower result=%+v calls=%d", got, calls.Load())
	}
	if got := <-follower2; got.Status != "ready" || calls.Load() != 1 {
		t.Fatalf("second follower result=%+v calls=%d", got, calls.Load())
	}
}

func TestWarmupShortDeadlineInitiatorDoesNotOwnSharedAttempt(t *testing.T) {
	c := newWarmupCoordinator()
	root := context.Background()
	entered, release := make(chan struct{}), make(chan struct{})
	fn := func(context.Context) warmupResult {
		close(entered)
		<-release
		return warmupResult{Operation: "tts", Status: "ready"}
	}
	shortCtx, shortCancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer shortCancel()
	short := make(chan warmupResult, 1)
	go func() { short <- c.run(shortCtx, root, time.Second, "tts", fn) }()
	<-entered
	longCtx := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
	long := make(chan warmupResult, 1)
	go func() { long <- c.run(longCtx, root, 2*time.Second, "tts", fn) }()
	waitForWarmupWaiter(t, longCtx)
	if got := <-short; got.Status != "warming" {
		t.Fatalf("short-deadline caller result=%+v", got)
	}
	close(release)
	if got := <-long; got.Status != "ready" {
		t.Fatalf("long-deadline caller lost shared result: %+v", got)
	}
}

func TestWarmupAllCallersMayLeaveWhileBoundedAttemptFinishes(t *testing.T) {
	c := newWarmupCoordinator()
	root := context.Background()
	entered, release := make(chan struct{}), make(chan struct{})
	var calls atomic.Int32
	fn := func(context.Context) warmupResult {
		calls.Add(1)
		close(entered)
		<-release
		return warmupResult{Operation: "text_transform", Status: "ready"}
	}
	ctx1, cancel1 := context.WithCancel(context.Background())
	first := make(chan warmupResult, 1)
	go func() { first <- c.run(ctx1, root, time.Second, "text_transform", fn) }()
	<-entered
	ctx2, cancel2 := context.WithCancel(context.Background())
	secondCtx := &notifyingContext{Context: ctx2, notified: make(chan struct{})}
	second := make(chan warmupResult, 1)
	go func() { second <- c.run(secondCtx, root, time.Second, "text_transform", fn) }()
	waitForWarmupWaiter(t, secondCtx)
	cancel1()
	cancel2()
	if (<-first).Status != "warming" || (<-second).Status != "warming" {
		t.Fatal("disconnected callers should stop waiting while attempt remains active")
	}
	lateCtx := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
	late := make(chan warmupResult, 1)
	go func() { late <- c.run(lateCtx, root, time.Second, "text_transform", fn) }()
	waitForWarmupWaiter(t, lateCtx)
	close(release)
	if got := <-late; got.Status != "ready" || calls.Load() != 1 {
		t.Fatalf("late waiter result=%+v calls=%d", got, calls.Load())
	}
}

func TestWarmupAttemptDeadlineAndGatewayShutdownCancelSharedWork(t *testing.T) {
	t.Run("attempt deadline", func(t *testing.T) {
		c := newWarmupCoordinator()
		result := c.run(context.Background(), context.Background(), 20*time.Millisecond, "stt", func(ctx context.Context) warmupResult {
			<-ctx.Done()
			return warmupResult{Operation: "stt", Status: "timed_out", Code: "deadline_exceeded"}
		})
		if result.Status != "timed_out" {
			t.Fatalf("result=%+v", result)
		}
	})
	t.Run("gateway shutdown", func(t *testing.T) {
		c := newWarmupCoordinator()
		root, shutdown := context.WithCancel(context.Background())
		entered := make(chan struct{})
		caller := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
		result := make(chan warmupResult, 1)
		go func() {
			result <- c.run(caller, root, time.Second, "stt", func(ctx context.Context) warmupResult {
				close(entered)
				<-ctx.Done()
				return warmupResult{Operation: "stt", Status: "unavailable", Code: "worker_unavailable"}
			})
		}()
		<-entered
		waitForWarmupWaiter(t, caller)
		shutdown()
		if got := <-result; got.Status != "unavailable" {
			t.Fatalf("shutdown result=%+v", got)
		}
	})
}

func TestWarmupDistinctOperationsRemainSerializedUntilUpstreamReturns(t *testing.T) {
	c := newWarmupCoordinator()
	root := context.Background()
	firstEntered, releaseFirst, secondEntered := make(chan struct{}), make(chan struct{}), make(chan struct{})
	first := make(chan warmupResult, 1)
	go func() {
		first <- c.run(context.Background(), root, time.Second, "stt", func(context.Context) warmupResult {
			close(firstEntered)
			<-releaseFirst
			return warmupResult{Operation: "stt", Status: "ready"}
		})
	}()
	<-firstEntered
	secondCtx := &notifyingContext{Context: context.Background(), notified: make(chan struct{})}
	second := make(chan warmupResult, 1)
	go func() {
		second <- c.run(secondCtx, root, time.Second, "tts", func(context.Context) warmupResult {
			close(secondEntered)
			return warmupResult{Operation: "tts", Status: "ready"}
		})
	}()
	waitForWarmupWaiter(t, secondCtx)
	select {
	case <-secondEntered:
		t.Fatal("distinct operation started before prior upstream call returned")
	default:
	}
	close(releaseFirst)
	if (<-first).Status != "ready" || (<-second).Status != "ready" {
		t.Fatal("serialized operations did not complete")
	}
}

type warmupRoundTripFunc func(*http.Request) (*http.Response, error)

func (f warmupRoundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}

func TestWarmupDeadlineMarksLaterOperationNotAttempted(t *testing.T) {
	for _, firstStatus := range []string{"ready", "timed_out"} {
		t.Run(firstStatus, func(t *testing.T) {
			// Advance only the admission clock after STT returns. The real request
			// context remains uncancelled, as when its timer notification is late.
			var expired atomic.Bool
			coordinator := newWarmupCoordinator()
			now := time.Now()
			coordinator.now = func() time.Time {
				if expired.Load() {
					return now.Add(3 * time.Hour)
				}
				return now
			}
			var sttCalls, ttsCalls atomic.Int32
			stt := NewSTTProxy("http://stt.invalid", "", time.Second)
			stt.Client.Transport = warmupRoundTripFunc(func(*http.Request) (*http.Response, error) {
				sttCalls.Add(1)
				expired.Store(true)
				status := http.StatusOK
				if firstStatus == "timed_out" {
					status = http.StatusGatewayTimeout
				}
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(`{"model_state":"ready"}`)), Header: make(http.Header)}, nil
			})
			tts := NewTTSProxy("http://tts.invalid", "", time.Second)
			tts.Client.Transport = warmupRoundTripFunc(func(*http.Request) (*http.Response, error) {
				ttsCalls.Add(1)
				return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(`{"model_state":"loaded","inference_active":false}`)), Header: make(http.Header)}, nil
			})
			r := httptest.NewRequest(http.MethodPost, "/v1/models/warmup", strings.NewReader(`{"operations":["stt","tts"]}`))
			r.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			serveWarmup(w, r, "", coordinator, make(chan struct{}, 4), stt, tts, nil, 2*time.Hour, context.Background())
			got := decodeWarmup(t, w)
			if w.Code != http.StatusOK || len(got.Results) != 2 || got.Complete || got.Results[0].Status != firstStatus || got.Results[1].Status != "not_attempted" || got.Results[1].Code != "deadline_exceeded" {
				t.Fatalf("status=%d result=%+v", w.Code, got)
			}
			if r.Context().Err() != nil || sttCalls.Load() != 1 || ttsCalls.Load() != 0 {
				t.Fatalf("err=%v stt calls=%d tts calls=%d", r.Context().Err(), sttCalls.Load(), ttsCalls.Load())
			}
		})
	}
}

func TestWarmupWorkerTimeoutBeforeTotalDeadlineAllowsLaterOperation(t *testing.T) {
	var ttsCalls atomic.Int32
	stt := NewSTTProxy("http://stt.invalid", "", time.Second)
	stt.Client.Transport = warmupRoundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusGatewayTimeout, Body: http.NoBody, Header: make(http.Header)}, nil
	})
	tts := NewTTSProxy("http://tts.invalid", "", time.Second)
	tts.Client.Transport = warmupRoundTripFunc(func(*http.Request) (*http.Response, error) {
		ttsCalls.Add(1)
		return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(strings.NewReader(`{"model_state":"loaded","inference_active":false}`)), Header: make(http.Header)}, nil
	})
	h := HandlerWithWarmupContext(Foundation{}, 1024, stt, tts, nil, time.Hour, context.Background())
	w := postWarmup(h, `{"operations":["stt","tts"]}`, "")
	got := decodeWarmup(t, w)
	if w.Code != http.StatusOK || len(got.Results) != 2 || got.Complete || got.Results[0].Status != "timed_out" || got.Results[1].Status != "ready" || ttsCalls.Load() != 1 {
		t.Fatalf("status=%d result=%+v tts calls=%d", w.Code, got, ttsCalls.Load())
	}
}

func TestWorkerWarmupSanitizesFailureAndMapsTimeout(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(503)
		_, _ = w.Write([]byte(`secret internal detail`))
	}))
	defer worker.Close()
	stt := NewSTTProxy(worker.URL, "", time.Second)
	got := stt.warmup(context.Background())
	if got.Status != "resource_unavailable" || strings.Contains(got.Code, "secret") {
		t.Fatalf("result=%+v", got)
	}
}
