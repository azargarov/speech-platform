package gateway

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type speechBody struct {
	read  func([]byte) (int, error)
	close func() error
}

func (b speechBody) Read(p []byte) (int, error) { return b.read(p) }
func (b speechBody) Close() error {
	if b.close != nil {
		return b.close()
	}
	return nil
}

func speechFixture(operation string, client *http.Client) (http.Handler, *http.Request) {
	stt := NewSTTProxy("http://worker.invalid", "", time.Hour)
	tts := NewTTSProxy("http://worker.invalid", "", time.Hour)
	stt.Client = client
	tts.Client = client
	path, content, body := "/v1/stt/transcriptions", "multipart/form-data; boundary=synthetic", "synthetic multipart"
	if operation == "tts" {
		path = "/v1/tts/speech"
		content = "application/json"
		body = `{"text":"Synthetic speech."}`
	}
	r := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	r.Header.Set("Content-Type", content)
	return HandlerWithWorkers(Foundation{}, 1024, stt, tts), r
}

func TestSpeechDeadlinesAndUnavailableAreDistinct(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		for _, kind := range []string{"expired", "deadline during body", "caller cancels body", "worker timeout", "worker unavailable", "response timeout", "success"} {
			t.Run(operation+"/"+kind, func(t *testing.T) {
				var calls atomic.Int32
				client := &http.Client{Transport: warmupRoundTripFunc(func(r *http.Request) (*http.Response, error) {
					calls.Add(1)
					// The caller's shorter budget wins over the configured one-hour timeout.
					if !validSpeechTimeoutHeader(r, 60000) {
						t.Errorf("remaining budget invalid: %q", r.Header.Get("X-Request-Timeout-Ms"))
					}
					switch kind {
					case "worker timeout":
						return nil, context.DeadlineExceeded
					case "worker unavailable":
						return nil, errors.New("private transport diagnostic")
					case "response timeout":
						return &http.Response{StatusCode: 200, Header: make(http.Header), Body: speechBody{read: func([]byte) (int, error) { return 0, context.DeadlineExceeded }}, ContentLength: -1}, nil
					}
					body, content := `{"text":"synthetic"}`, "application/json"
					if operation == "tts" {
						body = "synthetic wav"
						content = "audio/wav"
					}
					return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": []string{content}}, Body: io.NopCloser(strings.NewReader(body))}, nil
				})}
				h, r := speechFixture(operation, client)
				ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
				defer cancel()
				expected, wantedCalls := 200, int32(1)
				switch kind {
				case "expired":
					var stop context.CancelFunc
					ctx, stop = context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
					defer stop()
					expected, wantedCalls = 504, 0
				case "deadline during body":
					var stop context.CancelFunc
					ctx, stop = context.WithTimeout(context.Background(), 10*time.Millisecond)
					defer stop()
					r.Body = speechBody{read: func([]byte) (int, error) { <-ctx.Done(); return 0, io.ErrClosedPipe }}
					expected, wantedCalls = 504, 0
				case "caller cancels body":
					r.Body = speechBody{read: func([]byte) (int, error) { cancel(); return 0, io.ErrClosedPipe }}
					wantedCalls = 0 // No response is needed after caller cancellation.
				case "worker timeout", "response timeout":
					expected = 504
				case "worker unavailable":
					expected = 503
				}
				r = r.WithContext(ctx)
				w := httptest.NewRecorder()
				h.ServeHTTP(w, r)
				if w.Code != expected || calls.Load() != wantedCalls || strings.Contains(w.Body.String(), "private transport") {
					t.Fatalf("status=%d calls=%d body=%s", w.Code, calls.Load(), w.Body.String())
				}
			})
		}
	}
}

func TestSpeechHTTPWorkerTimeoutReturns504(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		t.Run(operation, func(t *testing.T) {
			var calls atomic.Int32
			worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				_, _ = io.Copy(io.Discard, r.Body)
				<-r.Context().Done()
			}))
			defer worker.Close()
			h, r := speechFixture(operation, &http.Client{Transport: warmupRoundTripFunc(func(req *http.Request) (*http.Response, error) {
				// Exercise the actual HTTP transport while keeping the public handler fixture.
				target := worker.URL + req.URL.Path
				upstream, err := http.NewRequestWithContext(req.Context(), req.Method, target, req.Body)
				if err != nil {
					return nil, err
				}
				upstream.Header = req.Header.Clone()
				return http.DefaultTransport.RoundTrip(upstream)
			})})
			ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
			defer cancel()
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r.WithContext(ctx))
			if w.Code != 504 || calls.Load() > 1 {
				t.Fatalf("status=%d calls=%d body=%s", w.Code, calls.Load(), w.Body.String())
			}
		})
	}
}

type blockedSpeechWriter struct {
	header           http.Header
	entered, stopped chan struct{}
	once             sync.Once
}

func (w *blockedSpeechWriter) Header() http.Header { return w.header }
func (w *blockedSpeechWriter) WriteHeader(int)     {}
func (w *blockedSpeechWriter) Write([]byte) (int, error) {
	close(w.entered)
	<-w.stopped
	return 0, context.DeadlineExceeded
}
func (w *blockedSpeechWriter) SetWriteDeadline(time.Time) error {
	w.once.Do(func() { close(w.stopped) })
	return nil
}

func TestSpeechCancellationBoundsStartedResponseDelivery(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		t.Run(operation, func(t *testing.T) {
			h, r := speechFixture(operation, &http.Client{Transport: warmupRoundTripFunc(func(*http.Request) (*http.Response, error) {
				content := "application/json"
				if operation == "tts" {
					content = "audio/wav"
				}
				return &http.Response{StatusCode: 200, Header: http.Header{"Content-Type": []string{content}}, Body: io.NopCloser(strings.NewReader("synthetic response"))}, nil
			})})
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			w := &blockedSpeechWriter{header: make(http.Header), entered: make(chan struct{}), stopped: make(chan struct{})}
			done := make(chan struct{})
			go func() { defer close(done); h.ServeHTTP(w, r.WithContext(ctx)) }()
			select {
			case <-w.entered:
			case <-time.After(time.Second):
				t.Fatal("delivery did not start")
			}
			cancel()
			select {
			case <-done:
			case <-time.After(time.Second):
				t.Fatal("cancelled response delivery remained blocked")
			}
		})
	}
}
