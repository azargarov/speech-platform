package gateway

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func admissionTestHandler(roundTripper http.RoundTripper) http.Handler {
	client := &http.Client{Transport: roundTripper}
	stt := NewSTTProxy("http://worker.invalid", "", time.Minute)
	tts := NewTTSProxy("http://worker.invalid", "", time.Minute)
	stt.Client = client
	tts.Client = client
	return HandlerWithWorkers(Foundation{}, 25*1024*1024, stt, tts)
}

func admissionRequest(operation string, body io.ReadCloser) *http.Request {
	path, contentType := "/v1/stt/transcriptions", "multipart/form-data; boundary=test"
	if operation == "tts" {
		path, contentType = "/v1/tts/speech", "application/json"
	}
	r := httptest.NewRequest(http.MethodPost, path, nil)
	r.Body = body
	r.ContentLength = -1
	r.Header.Set("Content-Type", contentType)
	return r
}

func admissionBody(operation string) io.ReadCloser {
	if operation == "tts" {
		return io.NopCloser(strings.NewReader(`{"text":"synthetic"}`))
	}
	return io.NopCloser(strings.NewReader("--test\r\nsynthetic audio\r\n--test--\r\n"))
}

func admissionWorkerResponse(operation string, request *http.Request) *http.Response {
	body, contentType := `{"text":"synthetic","transcription":"synthetic","language":"en"}`, "application/json"
	if operation == "tts" {
		body, contentType = "RIFF synthetic audio", "audio/wav"
	}
	return &http.Response{
		StatusCode:    http.StatusOK,
		Header:        http.Header{"Content-Type": []string{contentType}},
		Body:          io.NopCloser(strings.NewReader(body)),
		ContentLength: int64(len(body)),
		Request:       request,
	}
}

func waitAdmissionSignal(t *testing.T, signal <-chan struct{}, description string) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s", description)
	}
}

func releaseAdmissionSignal(signal chan struct{}) func() {
	var once sync.Once
	return func() { once.Do(func() { close(signal) }) }
}

func serveAdmissionRequest(h http.Handler, operation string, request *http.Request) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request)
	return w
}

func TestSTTAndTTSAdmissionIsIndependent(t *testing.T) {
	sttEntered, ttsEntered := make(chan struct{}), make(chan struct{})
	releaseSTT, releaseTTS := make(chan struct{}), make(chan struct{})
	releaseSTTCall := releaseAdmissionSignal(releaseSTT)
	releaseTTSCall := releaseAdmissionSignal(releaseTTS)
	defer releaseSTTCall()
	defer releaseTTSCall()
	var sttCalls, ttsCalls atomic.Int32
	h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch r.URL.Path {
		case "/internal/v1/transcriptions":
			if sttCalls.Add(1) == 1 {
				close(sttEntered)
				<-releaseSTT
			}
			return admissionWorkerResponse("stt", r), nil
		case "/internal/v1/speech":
			if ttsCalls.Add(1) == 1 {
				close(ttsEntered)
				<-releaseTTS
			}
			return admissionWorkerResponse("tts", r), nil
		default:
			return nil, errors.New("unexpected worker path")
		}
	}))

	sttDone, ttsDone := make(chan *httptest.ResponseRecorder, 1), make(chan *httptest.ResponseRecorder, 1)
	go func() { sttDone <- serveAdmissionRequest(h, "stt", admissionRequest("stt", admissionBody("stt"))) }()
	go func() { ttsDone <- serveAdmissionRequest(h, "tts", admissionRequest("tts", admissionBody("tts"))) }()
	waitAdmissionSignal(t, sttEntered, "first STT worker request")
	waitAdmissionSignal(t, ttsEntered, "first TTS worker request")

	waiters := map[string]chan *httptest.ResponseRecorder{
		"stt": make(chan *httptest.ResponseRecorder, sttRequestQueueCapacity+1),
		"tts": make(chan *httptest.ResponseRecorder, ttsRequestQueueCapacity+1),
	}
	for operation, count := range map[string]int{"stt": sttRequestQueueCapacity + 1, "tts": ttsRequestQueueCapacity + 1} {
		for range count {
			go func() {
				waiters[operation] <- serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
			}()
		}
	}
	for operation := range waiters {
		select {
		case response := <-waiters[operation]:
			if response.Code != http.StatusTooManyRequests || !strings.Contains(response.Body.String(), `"code":"overloaded"`) {
				t.Fatalf("full %s waiting queue status=%d body=%s", operation, response.Code, response.Body.String())
			}
		case <-time.After(2 * time.Second):
			t.Fatalf("full %s waiting queue did not reject the excess request", operation)
		}
	}

	releaseSTTCall()
	releaseTTSCall()
	var sttResponse, ttsResponse *httptest.ResponseRecorder
	select {
	case sttResponse = <-sttDone:
	case <-time.After(2 * time.Second):
		t.Fatal("first STT request did not finish after release")
	}
	select {
	case ttsResponse = <-ttsDone:
	case <-time.After(2 * time.Second):
		t.Fatal("first TTS request did not finish after release")
	}
	if response := sttResponse; response.Code != http.StatusOK {
		t.Fatalf("first STT status=%d body=%s", response.Code, response.Body.String())
	}
	if response := ttsResponse; response.Code != http.StatusOK {
		t.Fatalf("first TTS status=%d body=%s", response.Code, response.Body.String())
	}
	for operation, queuedCount := range map[string]int{"stt": sttRequestQueueCapacity, "tts": ttsRequestQueueCapacity} {
		for i := 0; i < queuedCount; i++ {
			select {
			case response := <-waiters[operation]:
				if response.Code != http.StatusOK {
					t.Fatalf("queued %s status=%d body=%s", operation, response.Code, response.Body.String())
				}
			case <-time.After(2 * time.Second):
				t.Fatalf("queued %s request %d did not run after release", operation, i)
			}
		}
	}
	if sttCalls.Load() != 1+sttRequestQueueCapacity || ttsCalls.Load() != 1+ttsRequestQueueCapacity {
		t.Fatalf("independent waiters did not reach workers: STT=%d TTS=%d", sttCalls.Load(), ttsCalls.Load())
	}
	for _, operation := range []string{"stt", "tts"} {
		response := serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
		if response.Code != http.StatusOK {
			t.Fatalf("%s admission did not recover: status=%d body=%s", operation, response.Code, response.Body.String())
		}
	}
}

func waitForAdmissionQueue(t *testing.T, admission *speechAdmission, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		admission.mu.Lock()
		got := len(admission.waiting)
		admission.mu.Unlock()
		if got == want {
			return
		}
		runtime.Gosched()
	}
	t.Fatalf("admission queue length did not reach %d", want)
}

func TestSpeechAdmissionFIFOAndQueueCapacity(t *testing.T) {
	admission := newSpeechAdmission(3)
	activeLease, full, err := admission.acquire(context.Background())
	if err != nil || full || activeLease == nil {
		t.Fatalf("active acquire release=%v full=%t err=%v", activeLease != nil, full, err)
	}
	defer activeLease.Release()

	type waiterResult struct {
		id    int
		lease *speechAdmissionLease
		err   error
	}
	acquired := make(chan waiterResult, 3)
	released := make(chan int, 3)
	turns := make([]chan struct{}, 3)
	turnRelease := make([]func(), 3)
	for i := range turns {
		turns[i] = make(chan struct{})
		turnRelease[i] = releaseAdmissionSignal(turns[i])
		defer turnRelease[i]()
		id := i
		go func() {
			lease, full, err := admission.acquire(context.Background())
			if full && err == nil {
				err = errors.New("unexpected full queue")
			}
			acquired <- waiterResult{id: id, lease: lease, err: err}
			if err == nil {
				<-turns[id]
				lease.Release()
				released <- id
			}
		}()
		waitForAdmissionQueue(t, admission, i+1)
	}
	if lease, queueFull, err := admission.acquire(context.Background()); err != nil || !queueFull || lease != nil {
		t.Fatalf("over-capacity acquire release=%v full=%t err=%v", lease != nil, queueFull, err)
	}

	for i := range turns {
		if i == 0 {
			activeLease.Release()
		}
		select {
		case got := <-acquired:
			if got.err != nil || got.lease == nil || got.id != i {
				t.Fatalf("FIFO turn %d got id=%d release=%v err=%v", i, got.id, got.lease != nil, got.err)
			}
			turnRelease[i]()
			select {
			case releasedID := <-released:
				if releasedID != i {
					t.Fatalf("released waiter %d while expecting %d", releasedID, i)
				}
			case <-time.After(2 * time.Second):
				t.Fatalf("FIFO waiter %d did not release", i)
			}
		case <-time.After(2 * time.Second):
			t.Fatalf("FIFO waiter %d was not promoted", i)
		}
	}
	waitForAdmissionQueue(t, admission, 0)
	if lease, queueFull, err := admission.acquire(context.Background()); err != nil || queueFull || lease == nil {
		t.Fatalf("admission did not recover: release=%v full=%t err=%v", lease != nil, queueFull, err)
	} else {
		lease.Release()
	}
}

func TestSpeechAdmissionCancellationAndDeadlineRemoveWaiters(t *testing.T) {
	admission := newSpeechAdmission(3)
	activeLease, _, _ := admission.acquire(context.Background())

	cancelCtx, cancel := context.WithCancel(context.Background())
	cancelDone := make(chan error, 1)
	go func() {
		_, _, err := admission.acquire(cancelCtx)
		cancelDone <- err
	}()
	waitForAdmissionQueue(t, admission, 1)
	cancel()
	select {
	case err := <-cancelDone:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("cancelled waiter error=%v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("cancelled waiter did not return")
	}
	waitForAdmissionQueue(t, admission, 0)

	deadlineCtx, deadlineCancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer deadlineCancel()
	deadlineDone := make(chan error, 1)
	go func() {
		_, _, err := admission.acquire(deadlineCtx)
		deadlineDone <- err
	}()
	waitForAdmissionQueue(t, admission, 1)
	select {
	case err := <-deadlineDone:
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("expired waiter error=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("deadline waiter did not return")
	}
	waitForAdmissionQueue(t, admission, 0)

	activeLease.Release()
	if lease, full, err := admission.acquire(context.Background()); err != nil || full || lease == nil {
		t.Fatalf("admission did not recover after waiter cancellation: release=%v full=%t err=%v", lease != nil, full, err)
	} else {
		lease.Release()
	}
}

type blockingInputBody struct {
	entered chan struct{}
	release chan struct{}
	data    []byte
	done    bool
}

func (b *blockingInputBody) Read(p []byte) (int, error) {
	if b.done {
		return 0, io.EOF
	}
	close(b.entered)
	<-b.release
	b.done = true
	return copy(p, b.data), nil
}
func (*blockingInputBody) Close() error { return nil }

type blockingOutputBody struct {
	entered chan struct{}
	release chan struct{}
	data    []byte
	done    bool
}

func (b *blockingOutputBody) Read(p []byte) (int, error) {
	if b.done {
		return 0, io.EOF
	}
	close(b.entered)
	<-b.release
	b.done = true
	return copy(p, b.data), nil
}
func (*blockingOutputBody) Close() error { return nil }

type countingRequestBody struct {
	reader io.Reader
	reads  atomic.Int32
}

func (b *countingRequestBody) Read(p []byte) (int, error) {
	b.reads.Add(1)
	return b.reader.Read(p)
}
func (*countingRequestBody) Close() error { return nil }

func TestIndependentAdmissionWhileOtherServiceHasSlowIO(t *testing.T) {
	t.Run("TTS available during STT upload", func(t *testing.T) {
		var ttsCalls atomic.Int32
		h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.URL.Path == "/internal/v1/speech" {
				ttsCalls.Add(1)
				return admissionWorkerResponse("tts", r), nil
			}
			if r.URL.Path != "/internal/v1/transcriptions" {
				return nil, errors.New("unexpected worker path")
			}
			return admissionWorkerResponse("stt", r), nil
		}))
		entered, release := make(chan struct{}), make(chan struct{})
		releaseIO := releaseAdmissionSignal(release)
		defer releaseIO()
		sttRequest := admissionRequest("stt", &blockingInputBody{
			entered: entered, release: release,
			data: []byte("--test\r\nsynthetic audio\r\n--test--\r\n"),
		})
		sttDone := make(chan *httptest.ResponseRecorder, 1)
		go func() { sttDone <- serveAdmissionRequest(h, "stt", sttRequest) }()
		waitAdmissionSignal(t, entered, "STT upload read")

		ttsResponse := serveAdmissionRequest(h, "tts", admissionRequest("tts", admissionBody("tts")))
		if ttsResponse.Code != http.StatusOK || ttsCalls.Load() != 1 {
			t.Fatalf("TTS blocked by STT upload: status=%d calls=%d body=%s", ttsResponse.Code, ttsCalls.Load(), ttsResponse.Body.String())
		}
		releaseIO()
		select {
		case response := <-sttDone:
			if response.Code != http.StatusOK {
				t.Fatalf("STT upload did not complete: status=%d body=%s", response.Code, response.Body.String())
			}
		case <-time.After(2 * time.Second):
			t.Fatal("STT upload did not finish after release")
		}
	})

	t.Run("STT available during TTS response read", func(t *testing.T) {
		entered, release := make(chan struct{}), make(chan struct{})
		releaseIO := releaseAdmissionSignal(release)
		defer releaseIO()
		var sttCalls atomic.Int32
		h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.URL.Path == "/internal/v1/transcriptions" {
				sttCalls.Add(1)
				return admissionWorkerResponse("stt", r), nil
			}
			body := &blockingOutputBody{entered: entered, release: release, data: []byte("RIFF synthetic")}
			return &http.Response{
				StatusCode: http.StatusOK, Header: http.Header{"Content-Type": []string{"audio/wav"}},
				Body: body, ContentLength: int64(len(body.data)), Request: r,
			}, nil
		}))
		ttsDone := make(chan *httptest.ResponseRecorder, 1)
		go func() { ttsDone <- serveAdmissionRequest(h, "tts", admissionRequest("tts", admissionBody("tts"))) }()
		waitAdmissionSignal(t, entered, "TTS response read")

		sttResponse := serveAdmissionRequest(h, "stt", admissionRequest("stt", admissionBody("stt")))
		if sttResponse.Code != http.StatusOK || sttCalls.Load() != 1 {
			t.Fatalf("STT blocked by TTS response read: status=%d calls=%d body=%s", sttResponse.Code, sttCalls.Load(), sttResponse.Body.String())
		}
		releaseIO()
		select {
		case response := <-ttsDone:
			if response.Code != http.StatusOK {
				t.Fatalf("TTS response did not complete: status=%d body=%s", response.Code, response.Body.String())
			}
		case <-time.After(2 * time.Second):
			t.Fatal("TTS response did not finish after release")
		}
	})
}

func TestAdmissionRecoversAfterWorkerFailureAndDeadline(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		for _, failure := range []string{"worker error", "deadline"} {
			t.Run(operation+"/"+failure, func(t *testing.T) {
				var calls atomic.Int32
				entered := make(chan struct{})
				h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
					if calls.Add(1) == 1 {
						if failure == "worker error" {
							return nil, errors.New("private synthetic diagnostic")
						}
						close(entered)
						<-r.Context().Done()
						return nil, r.Context().Err()
					}
					return admissionWorkerResponse(operation, r), nil
				}))

				request := admissionRequest(operation, admissionBody(operation))
				var cancel context.CancelFunc
				if failure == "deadline" {
					var ctx context.Context
					ctx, cancel = context.WithTimeout(request.Context(), 50*time.Millisecond)
					defer cancel()
					request = request.WithContext(ctx)
				}
				firstDone := make(chan *httptest.ResponseRecorder, 1)
				go func() { firstDone <- serveAdmissionRequest(h, operation, request) }()
				if failure == "deadline" {
					waitAdmissionSignal(t, entered, "timed worker request")
				}
				var first *httptest.ResponseRecorder
				select {
				case first = <-firstDone:
				case <-time.After(2 * time.Second):
					t.Fatal("failed or expired request did not return")
				}
				if failure == "worker error" && first.Code != http.StatusServiceUnavailable {
					t.Fatalf("worker error status=%d body=%s", first.Code, first.Body.String())
				}
				if strings.Contains(first.Body.String(), "private synthetic diagnostic") {
					t.Fatalf("worker diagnostic escaped sanitization: %s", first.Body.String())
				}
				if failure == "deadline" && first.Code != http.StatusGatewayTimeout {
					t.Fatalf("deadline status=%d body=%s", first.Code, first.Body.String())
				}
				second := serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
				if second.Code != http.StatusOK || calls.Load() != 2 {
					t.Fatalf("%s admission did not recover: status=%d calls=%d body=%s", operation, second.Code, calls.Load(), second.Body.String())
				}
			})
		}
	}
}

func TestAdmissionRecoversAfterClientCancellation(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		t.Run(operation, func(t *testing.T) {
			var calls atomic.Int32
			entered := make(chan struct{})
			h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if calls.Add(1) == 1 {
					close(entered)
					<-r.Context().Done()
					return nil, r.Context().Err()
				}
				return admissionWorkerResponse(operation, r), nil
			}))
			ctx, cancel := context.WithCancel(context.Background())
			request := admissionRequest(operation, admissionBody(operation)).WithContext(ctx)
			firstDone := make(chan *httptest.ResponseRecorder, 1)
			go func() { firstDone <- serveAdmissionRequest(h, operation, request) }()
			waitAdmissionSignal(t, entered, "active worker request")
			cancel()
			select {
			case <-firstDone:
			case <-time.After(2 * time.Second):
				t.Fatal("cancelled request did not release its admission slot")
			}
			second := serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
			if second.Code != http.StatusOK || calls.Load() != 2 {
				t.Fatalf("%s admission did not recover after cancellation: status=%d calls=%d body=%s", operation, second.Code, calls.Load(), second.Body.String())
			}
		})
	}
}

func TestQueuedSpeechDeadlineReturns504WithoutReadingOrDispatching(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		t.Run(operation, func(t *testing.T) {
			var calls atomic.Int32
			entered, release := make(chan struct{}), make(chan struct{})
			releaseCall := releaseAdmissionSignal(release)
			defer releaseCall()
			h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if calls.Add(1) == 1 {
					close(entered)
					<-release
				}
				return admissionWorkerResponse(operation, r), nil
			}))
			firstDone := make(chan *httptest.ResponseRecorder, 1)
			go func() {
				firstDone <- serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
			}()
			waitAdmissionSignal(t, entered, "active "+operation+" worker request")

			requestBody := &countingRequestBody{reader: strings.NewReader(stringBody(operation))}
			request := admissionRequest(operation, requestBody)
			ctx, cancel := context.WithTimeout(request.Context(), 30*time.Millisecond)
			defer cancel()
			request = request.WithContext(ctx)
			queuedDone := make(chan *httptest.ResponseRecorder, 1)
			go func() { queuedDone <- serveAdmissionRequest(h, operation, request) }()
			select {
			case response := <-queuedDone:
				if response.Code != http.StatusGatewayTimeout {
					t.Fatalf("queued request status=%d body=%s", response.Code, response.Body.String())
				}
			case <-time.After(2 * time.Second):
				t.Fatal("queued request did not honor its deadline")
			}
			if requestBody.reads.Load() != 0 || calls.Load() != 1 {
				t.Fatalf("expired waiter started work: body reads=%d worker calls=%d", requestBody.reads.Load(), calls.Load())
			}

			releaseCall()
			select {
			case response := <-firstDone:
				if response.Code != http.StatusOK {
					t.Fatalf("active request status=%d body=%s", response.Code, response.Body.String())
				}
			case <-time.After(2 * time.Second):
				t.Fatal("active request did not finish after release")
			}
		})
	}
}

func TestQueuedSpeechWaitersExitOnCancellationAndGatewayShutdown(t *testing.T) {
	for _, operation := range []string{"stt", "tts"} {
		for _, ending := range []string{"client cancellation", "gateway shutdown"} {
			t.Run(operation+"/"+ending, func(t *testing.T) {
				root, shutdown := context.WithCancel(context.Background())
				defer shutdown()
				entered, release := make(chan struct{}), make(chan struct{})
				releaseCall := releaseAdmissionSignal(release)
				defer releaseCall()
				var calls atomic.Int32
				client := &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
					if calls.Add(1) == 1 {
						close(entered)
						<-release
					}
					return admissionWorkerResponse(operation, r), nil
				})}
				stt := NewSTTProxy("http://worker.invalid", "", time.Minute)
				tts := NewTTSProxy("http://worker.invalid", "", time.Minute)
				stt.Client, tts.Client = client, client
				h := HandlerWithWarmupContext(Foundation{}, 25*1024*1024, stt, tts, nil, time.Minute, root)

				activeDone := make(chan *httptest.ResponseRecorder, 1)
				go func() {
					activeDone <- serveAdmissionRequest(h, operation, admissionRequest(operation, admissionBody(operation)))
				}()
				waitAdmissionSignal(t, entered, "active "+operation+" request")

				queueCapacity := sttRequestQueueCapacity
				if operation == "tts" {
					queueCapacity = ttsRequestQueueCapacity
				}
				type queuedResponse struct {
					index    int
					response *httptest.ResponseRecorder
				}
				responses := make(chan queuedResponse, queueCapacity+1)
				cancels := make([]context.CancelFunc, 0, queueCapacity+1)
				for i := 0; i < queueCapacity+1; i++ {
					ctx, cancel := context.WithCancel(context.Background())
					request := admissionRequest(operation, admissionBody(operation)).WithContext(ctx)
					index := i
					cancels = append(cancels, cancel)
					go func() {
						responses <- queuedResponse{index: index, response: serveAdmissionRequest(h, operation, request)}
					}()
				}

				var overflow queuedResponse
				select {
				case overflow = <-responses:
					if overflow.response.Code != http.StatusTooManyRequests || !strings.Contains(overflow.response.Body.String(), `"code":"overloaded"`) {
						t.Fatalf("queue-full response status=%d body=%s", overflow.response.Code, overflow.response.Body.String())
					}
				case <-time.After(2 * time.Second):
					t.Fatal("bounded queue did not return its overload response")
				}

				if ending == "client cancellation" {
					for _, cancel := range cancels {
						cancel()
					}
				} else {
					shutdown()
				}
				for i := 0; i < queueCapacity; i++ {
					select {
					case event := <-responses:
						if event.index == overflow.index {
							t.Fatalf("overflow request unexpectedly completed twice: index=%d", event.index)
						}
						if ending == "gateway shutdown" && event.response.Code != http.StatusServiceUnavailable {
							t.Fatalf("shutdown waiter status=%d body=%s", event.response.Code, event.response.Body.String())
						}
					case <-time.After(2 * time.Second):
						t.Fatalf("queued waiter did not exit on %s", ending)
					}
				}
				for _, cancel := range cancels {
					cancel()
				}
				if calls.Load() != 1 {
					t.Fatalf("waiting requests dispatched during %s: worker calls=%d", ending, calls.Load())
				}

				releaseCall()
				select {
				case response := <-activeDone:
					if response.Code != http.StatusOK {
						t.Fatalf("active request status=%d body=%s", response.Code, response.Body.String())
					}
				case <-time.After(2 * time.Second):
					t.Fatal("active request did not complete after release")
				}
			})
		}
	}
}

func TestHTTPServerShutdownClosesSpeechQueueButDoesNotCancelActiveRequest(t *testing.T) {
	root, cancelRoot := context.WithCancel(context.Background())
	defer cancelRoot()
	workerEntered, releaseWorker := make(chan struct{}), make(chan struct{})
	releaseWorkerCall := releaseAdmissionSignal(releaseWorker)
	defer releaseWorkerCall()
	var workerCalls atomic.Int32
	stt := NewSTTProxy("http://worker.invalid", "", time.Minute)
	stt.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if workerCalls.Add(1) == 1 {
			close(workerEntered)
			<-releaseWorker
		}
		return admissionWorkerResponse("stt", r), nil
	})}
	h := HandlerWithWarmupContext(Foundation{}, 25*1024*1024, stt, nil, nil, time.Minute, root)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: h}
	serveDone := make(chan error, 1)
	go func() { serveDone <- srv.Serve(listener) }()
	defer func() {
		releaseWorkerCall()
		_ = srv.Close()
	}()

	client := &http.Client{Timeout: 5 * time.Second}
	endpoint := "http://" + listener.Addr().String() + "/v1/stt/transcriptions"
	request := func() *http.Request {
		t.Helper()
		r, err := http.NewRequest(http.MethodPost, endpoint, strings.NewReader("--test\r\nsynthetic audio\r\n--test--\r\n"))
		if err != nil {
			t.Fatal(err)
		}
		r.Header.Set("Content-Type", "multipart/form-data; boundary=test")
		return r
	}
	type result struct {
		status int
		body   string
	}
	doRequest := func() result {
		response, err := client.Do(request())
		if err != nil {
			return result{status: 0, body: err.Error()}
		}
		defer response.Body.Close()
		body, _ := io.ReadAll(response.Body)
		return result{status: response.StatusCode, body: string(body)}
	}
	activeDone := make(chan result, 1)
	go func() { activeDone <- doRequest() }()
	waitAdmissionSignal(t, workerEntered, "active HTTP STT request")

	queued := make(chan result, sttRequestQueueCapacity+1)
	for range sttRequestQueueCapacity + 1 {
		go func() { queued <- doRequest() }()
	}
	var overflowSeen bool
	for i := 0; i < sttRequestQueueCapacity+1; i++ {
		select {
		case got := <-queued:
			if got.status == http.StatusTooManyRequests {
				overflowSeen = true
				if !strings.Contains(got.body, `"code":"overloaded"`) {
					t.Fatalf("queue overflow body was not sanitized: %s", got.body)
				}
				break
			}
			if got.status != http.StatusTooManyRequests {
				t.Fatalf("queued request completed before shutdown: status=%d body=%s", got.status, got.body)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("HTTP queue did not report bounded capacity")
		}
		if overflowSeen {
			break
		}
	}
	if !overflowSeen {
		t.Fatal("did not observe the expected full-queue response")
	}

	cancelRoot()
	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancelShutdown()
	shutdownDone := make(chan error, 1)
	go func() { shutdownDone <- srv.Shutdown(shutdownCtx) }()

	shutdownWaiters := 0
	for shutdownWaiters < sttRequestQueueCapacity {
		select {
		case got := <-queued:
			if got.status != http.StatusServiceUnavailable || !strings.Contains(got.body, `"code":"not_ready"`) {
				t.Fatalf("queued HTTP request was not released on shutdown: status=%d body=%s", got.status, got.body)
			}
			shutdownWaiters++
		case <-time.After(2 * time.Second):
			t.Fatal("Gateway shutdown did not release all queued HTTP requests")
		}
	}
	if workerCalls.Load() != 1 {
		t.Fatalf("shutdown dispatched queued work: worker calls=%d", workerCalls.Load())
	}
	select {
	case got := <-activeDone:
		t.Fatalf("http.Server.Shutdown unexpectedly cancelled active request: %+v", got)
	default:
	}
	select {
	case err := <-shutdownDone:
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("shutdown with a blocked active request returned %v, want deadline", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("bounded HTTP server shutdown did not return")
	}

	releaseWorkerCall()
	select {
	case got := <-activeDone:
		if got.status != http.StatusOK {
			t.Fatalf("active request failed after release: status=%d body=%s", got.status, got.body)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("active HTTP request did not finish after worker release")
	}
	cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cleanupCancel()
	if err := srv.Shutdown(cleanupCtx); err != nil {
		t.Fatalf("server did not finish graceful shutdown after active request returned: %v", err)
	}
	select {
	case err := <-serveDone:
		if !errors.Is(err, http.ErrServerClosed) {
			t.Fatalf("Serve returned %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Serve did not exit after shutdown")
	}
	if workerCalls.Load() != 1 {
		t.Fatalf("worker calls changed after shutdown completion: %d", workerCalls.Load())
	}
}

func stringBody(operation string) string {
	if operation == "tts" {
		return `{"text":"synthetic"}`
	}
	return "--test\r\nsynthetic audio\r\n--test--\r\n"
}

func TestTTSDeclaredOversizeResponseIsSanitizedAndReleasesCapacity(t *testing.T) {
	var calls atomic.Int32
	h := admissionTestHandler(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if calls.Add(1) == 1 {
			return &http.Response{
				StatusCode:    http.StatusOK,
				Header:        http.Header{"Content-Type": []string{"audio/wav"}},
				Body:          io.NopCloser(strings.NewReader("private synthetic body")),
				ContentLength: maxTTSResponseBytes + 1, Request: r,
			}, nil
		}
		return admissionWorkerResponse("tts", r), nil
	}))
	first := serveAdmissionRequest(h, "tts", admissionRequest("tts", admissionBody("tts")))
	if first.Code != http.StatusBadGateway || !strings.Contains(first.Body.String(), `"code":"invalid_worker_response"`) || strings.Contains(first.Body.String(), "private synthetic") {
		t.Fatalf("oversize response was not bounded and sanitized: status=%d body=%s", first.Code, first.Body.String())
	}
	second := serveAdmissionRequest(h, "tts", admissionRequest("tts", admissionBody("tts")))
	if second.Code != http.StatusOK || calls.Load() != 2 {
		t.Fatalf("TTS admission did not recover after oversized response: status=%d calls=%d body=%s", second.Code, calls.Load(), second.Body.String())
	}
}
