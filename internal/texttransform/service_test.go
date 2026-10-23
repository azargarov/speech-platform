package texttransform

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"speech-platform/internal/config"
)

type fakeGenerator struct {
	calls   []string
	inputs  []string
	options []string
	fail    map[string]error
	output  string
	started chan struct{}
}

func (f *fakeGenerator) Generate(ctx context.Context, _ config.TextProvider, m config.TextModel, _, _, input, options string) (string, error) {
	f.calls = append(f.calls, m.ID)
	f.inputs = append(f.inputs, input)
	f.options = append(f.options, options)
	if f.started != nil {
		select {
		case f.started <- struct{}{}:
		default:
		}
	}
	if e := f.fail[m.ID]; e != nil {
		return "", e
	}
	if f.output != "" {
		return f.output, nil
	}
	return "generated", nil
}

func TestTransformationModesFormatsAndLanguagesReachFakeProvider(t *testing.T) {
	for _, mode := range []string{"written", "polite", "diplomatic"} {
		for _, format := range []string{"normal", "concise", "structured"} {
			for _, language := range []string{"none", "en", "sv", "ru"} {
				t.Run(mode+"/"+format+"/"+language, func(t *testing.T) {
					cfg := testConfig()
					g := &fakeGenerator{output: "synthetic fake result"}
					s, err := New(context.Background(), &cfg, "", g)
					if err != nil {
						t.Fatal(err)
					}
					defer s.Close()
					body, err := json.Marshal(map[string]string{
						"text": "Synthetic meeting note; date remains November 18.",
						"mode": mode, "format": format, "target_language": language,
					})
					if err != nil {
						t.Fatal(err)
					}
					status, response := call(t, s, string(body), false)
					if status != http.StatusOK || len(g.calls) != 1 || g.calls[0] != "local-model" {
						t.Fatalf("status=%d calls=%v response=%s", status, g.calls, response)
					}
					var options map[string]string
					if err := json.Unmarshal([]byte(g.options[0]), &options); err != nil {
						t.Fatal(err)
					}
					if options["mode"] != mode || options["format"] != format || options["target_language"] != language {
						t.Fatalf("provider options=%v", options)
					}
				})
			}
		}
	}
}

func TestExplicitSelectionUsesEachConfiguredModelWithoutFallback(t *testing.T) {
	t.Setenv("GROQ_API_KEY", "offline-fake-credential")
	cfg, err := config.Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	cfg.TextTransform.Selection.AllowCloud = true
	for _, id := range []string{"local-qwen", "groq-qwen", "groq-gpt-oss"} {
		t.Run(id, func(t *testing.T) {
			g := &fakeGenerator{output: "synthetic fake result"}
			s, err := New(context.Background(), cfg.TextTransform, "", g)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			body, err := json.Marshal(map[string]string{"text": "Synthetic input", "mode": "written", "model": id})
			if err != nil {
				t.Fatal(err)
			}
			status, raw := call(t, s, string(body), false)
			if status != http.StatusOK || !reflect.DeepEqual(g.calls, []string{id}) {
				t.Fatalf("status=%d calls=%v response=%s", status, g.calls, raw)
			}
			var response Response
			if err := json.Unmarshal(raw, &response); err != nil {
				t.Fatal(err)
			}
			if response.Model == nil || *response.Model != id || response.FallbackOccurred {
				t.Fatalf("response metadata=%#v", response)
			}
		})
	}
}

func testConfig() config.TextTransform {
	trueValue := true
	zero := 0.0
	top := 1.0
	seed := int32(1)
	n := 1024
	think := false
	return config.TextTransform{Enabled: &trueValue, RequestTimeout: "2s", MaxRequestBytes: 65536, MaxInputBytes: 10000, MaxOutputCharacters: 20000, MaxResponseBytes: 262144, MaxConcurrentRequests: 1, Selection: config.TextSelection{Policy: "ordered", AllowCloud: true}, Transport: config.TextTransport{ConnectTimeout: "1s", TLSHandshakeTimeout: "1s", MaxIdleConnections: 2}, Providers: []config.TextProvider{{ID: "local", Type: "ollama", Locality: "local", Endpoint: "http://local.invalid/api/generate", Timeout: "1s"}, {ID: "cloud", Type: "openai_compatible", Locality: "cloud", Endpoint: "https://cloud.invalid/v1/chat/completions", Timeout: "1s"}}, Models: []config.TextModel{{ID: "local-model", Provider: "local", Model: "local:tag", Enabled: &trueValue, ContextLimitTokens: 4096, PromptOverheadTokens: 64, Parameters: config.TextModelParameters{Ollama: &config.OllamaParameters{Think: &think, NumPredict: n, NumBatch: 128, NumThread: 4, Temperature: &zero, TopP: &top, Seed: &seed}}}, {ID: "cloud-model", Provider: "cloud", Model: "cloud-model", Enabled: &trueValue, ContextLimitTokens: 8192, PromptOverheadTokens: 64, Parameters: config.TextModelParameters{OpenAI: &config.OpenAIParameters{MaxCompletionTokens: &n, Temperature: &zero, TopP: &top, Seed: &seed}}}}}
}
func call(t *testing.T, h http.Handler, body string, auth bool) (int, []byte) {
	t.Helper()
	r := httptest.NewRequest(http.MethodPost, "/v1/text/transformations", strings.NewReader(body))
	r.Header.Set("Content-Type", "application/json")
	if auth {
		r.Header.Set("Authorization", "Bearer 01234567890123456789012345678901")
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w.Code, w.Body.Bytes()
}

func TestRawPassthroughIsExactAndSkipsGenerator(t *testing.T) {
	g := &fakeGenerator{}
	s, _ := New(context.Background(), ptr(testConfig()), "", g)
	defer s.Close()
	input := "line one\r\n  line two  "
	status, b := call(t, s, `{"text":"line one\r\n  line two  "}`, false)
	if status != 200 {
		t.Fatalf("status %d: %s", status, b)
	}
	var got Response
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	if got.TransformedText != input || got.Generated || got.Model != nil || len(g.calls) != 0 {
		t.Fatalf("unexpected raw result %#v calls=%v", got, g.calls)
	}
}
func TestAutomaticFallbackIsOrderedAndReported(t *testing.T) {
	cfg := testConfig()
	g := &fakeGenerator{fail: map[string]error{"local-model": &ProviderError{Kind: FailureTransport}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, b := call(t, s, `{"text":"please rewrite","mode":"written"}`, false)
	if status != 200 {
		t.Fatalf("status %d: %s", status, b)
	}
	var got Response
	_ = json.Unmarshal(b, &got)
	if !reflect.DeepEqual(g.calls, []string{"local-model", "cloud-model"}) || !got.FallbackOccurred || got.Model == nil || *got.Model != "cloud-model" {
		t.Fatalf("calls=%v result=%#v", g.calls, got)
	}
}
func TestSelectionPoliciesAreStableAndLocalOnlyTightensPermission(t *testing.T) {
	for _, tc := range []struct {
		policy string
		want   []string
	}{{"ordered", []string{"local-model", "cloud-model"}}, {"local_first", []string{"local-model", "cloud-model"}}, {"cloud_first", []string{"cloud-model"}}} {
		cfg := testConfig()
		cfg.Selection.Policy = tc.policy
		g := &fakeGenerator{fail: map[string]error{"local-model": &ProviderError{Kind: FailureTransport}}}
		s, _ := New(context.Background(), &cfg, "", g)
		status, _ := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
		s.Close()
		if status != 200 || !reflect.DeepEqual(g.calls, tc.want) {
			t.Errorf("policy=%s status=%d calls=%v", tc.policy, status, g.calls)
		}
	}
	cfg := testConfig()
	g := &fakeGenerator{fail: map[string]error{"local-model": &ProviderError{Kind: FailureTransport}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written","local_only":true}`, false)
	if status != 503 || !reflect.DeepEqual(g.calls, []string{"local-model"}) {
		t.Fatalf("local_only status=%d calls=%v", status, g.calls)
	}
}
func TestExplicitSelectionDoesNotFallback(t *testing.T) {
	cfg := testConfig()
	g := &fakeGenerator{fail: map[string]error{"local-model": &ProviderError{Kind: FailureTransport}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written","model":"local-model"}`, false)
	if status != 503 || !reflect.DeepEqual(g.calls, []string{"local-model"}) {
		t.Fatalf("status=%d calls=%v", status, g.calls)
	}
}
func TestLocalOnlyAndCloudPolicyPreventCloudCalls(t *testing.T) {
	cfg := testConfig()
	cfg.Selection.AllowCloud = false
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written","model":"cloud-model"}`, false)
	if status != 403 || len(g.calls) != 0 {
		t.Fatalf("status=%d calls=%v", status, g.calls)
	}
}
func TestProviderWide429SuppressesSameProviderModels(t *testing.T) {
	cfg := testConfig()
	cfg.Selection.Policy = "cloud_first"
	extra := cfg.Models[1]
	extra.ID = "cloud-second"
	extra.Model = "second-model"
	cfg.Models = append(cfg.Models, extra)
	g := &fakeGenerator{fail: map[string]error{"cloud-model": &ProviderError{Kind: FailureUnavailable, Suppress: true}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
	if status != 200 || !reflect.DeepEqual(g.calls, []string{"cloud-model", "local-model"}) {
		t.Fatalf("status=%d calls=%v", status, g.calls)
	}
}
func TestMixedFailureExhaustionHasDeterministicPrecedence(t *testing.T) {
	cfg := testConfig()
	g := &fakeGenerator{fail: map[string]error{"local-model": &ProviderError{Kind: FailureInvalidResponse}, "cloud-model": &ProviderError{Kind: FailureRejected, Suppress: true}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, b := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
	if status != 502 || !strings.Contains(string(b), "invalid_provider_response") {
		t.Fatalf("status=%d body=%s", status, b)
	}
}
func TestModelOnly429AllowsNextModelOnSameProvider(t *testing.T) {
	cfg := testConfig()
	cfg.Selection.Policy = "cloud_first"
	extra := cfg.Models[1]
	extra.ID = "cloud-second"
	extra.Model = "second-model"
	cfg.Models = append(cfg.Models, extra)
	g := &fakeGenerator{fail: map[string]error{"cloud-model": &ProviderError{Kind: FailureUnavailable}}}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, b := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
	var got Response
	_ = json.Unmarshal(b, &got)
	if status != 200 || !reflect.DeepEqual(g.calls, []string{"cloud-model", "cloud-second"}) || !got.FallbackOccurred {
		t.Fatalf("status=%d calls=%v result=%#v", status, g.calls, got)
	}
}
func TestMissingCloudCredentialIsUnavailableAndNeverCalls(t *testing.T) {
	cfg := testConfig()
	cfg.Providers[1].APIKeyEnv = "M05B_TEST_MISSING_KEY"
	t.Setenv("M05B_TEST_MISSING_KEY", "")
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written","model":"cloud-model"}`, false)
	if status != 503 || len(g.calls) != 0 {
		t.Fatalf("status=%d calls=%v", status, g.calls)
	}
}
func TestBearerBeforeDisabledCheck(t *testing.T) {
	cfg := testConfig()
	cfg.Enabled = nil
	s, _ := New(context.Background(), &cfg, "01234567890123456789012345678901", nil)
	defer s.Close()
	status, _ := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
	if status != 401 {
		t.Fatalf("status=%d", status)
	}
	status, _ = call(t, s, `{"text":"rewrite","mode":"written"}`, true)
	if status != 503 {
		t.Fatalf("status=%d", status)
	}
}
func TestRejectDuplicateKeysAndLoneSurrogates(t *testing.T) {
	cfg := testConfig()
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	for _, body := range []string{`{"text":"a","text":"b","mode":"written"}`, `{"text":"\uD800","mode":"written"}`, `{"text":"a","target_language":null,"mode":"written"}`} {
		status, _ := call(t, s, body, false)
		if status != 400 {
			t.Errorf("body %s status=%d", body, status)
		}
	}
	if len(g.calls) != 0 {
		t.Fatalf("provider called: %v", g.calls)
	}
}
func TestContextRejectionMakesNoCall(t *testing.T) {
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	cfg.Models[0].ContextLimitTokens = len(systemPrompt) + len(userPrompt("", `{"format":"normal","mode":"raw","target_language":"none"}`)) + 512 + cfg.Models[0].PromptOverheadTokens + outputBudget(cfg.Models[0])
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ := call(t, s, `{"text":"this definitely cannot fit the fixed prompt","mode":"written"}`, false)
	if status != 413 || len(g.calls) != 0 {
		t.Fatalf("status=%d calls=%v", status, g.calls)
	}
}

func TestValidateConfigRejectsFixedPromptThatCannotFit(t *testing.T) {
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	cfg.Models[0].ContextLimitTokens = 16
	if err := ValidateConfig(&cfg); err == nil {
		t.Fatal("fixed prompt exceeded configured context without error")
	}
}
func TestContextBoundaryAndMultilingualInputAreNotTruncated(t *testing.T) {
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	input := "åäö Привет 😀"
	need := len(systemPrompt) + len(userPrompt(input, `{"format":"normal","mode":"written","target_language":"none"}`)) + 512 + cfg.Models[0].PromptOverheadTokens + outputBudget(cfg.Models[0])
	cfg.Models[0].ContextLimitTokens = need
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	status, _ := call(t, s, `{"text":"åäö Привет 😀","mode":"written"}`, false)
	s.Close()
	if status != 200 || len(g.calls) != 1 || g.inputs[0] != input {
		t.Fatalf("boundary request status=%d calls=%v inputs=%q", status, g.calls, g.inputs)
	}
	cfg.Models[0].ContextLimitTokens = need
	g = &fakeGenerator{}
	s, _ = New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ = call(t, s, `{"text":"xåäö Привет 😀","mode":"written"}`, false)
	if status != 413 || len(g.calls) != 0 {
		t.Fatalf("over-boundary status=%d calls=%v", status, g.calls)
	}
}

func TestExampleLocalSerializedInputBudget(t *testing.T) {
	options := optionsJSON("raw", "normal", "none")
	const contextLimit, framing, promptOverhead, outputReservation = 8192, 512, 512, 1024
	budget := contextLimit - framing - promptOverhead - outputReservation - len([]byte(systemPrompt)) - len([]byte(userPrompt("", options)))
	if budget != 4963 {
		t.Fatalf("example local serialized input budget = %d bytes, want 4963; update this boundary when prompt or example budgets change", budget)
	}
}

func TestEightKContextAcceptsLongDictationRejectedAtFourK(t *testing.T) {
	// Representative longer dictated request, intentionally synthetic and offline.
	input := strings.Repeat("Please move the review meeting to Thursday afternoon, keep the budget at 1250 dollars, and tell Maria that the delivery date remains November 18. ", 12)
	request, err := json.Marshal(map[string]string{"text": input, "mode": "written"})
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		limit int
		want  int
		calls int
	}{{"4K rejects", 4096, http.StatusRequestEntityTooLarge, 0}, {"8K accepts", 8192, http.StatusOK, 1}} {
		t.Run(tc.name, func(t *testing.T) {
			cfg := testConfig()
			cfg.Models = cfg.Models[:1]
			cfg.Models[0].ContextLimitTokens = tc.limit
			cfg.Models[0].PromptOverheadTokens = 512
			g := &fakeGenerator{}
			s, err := New(context.Background(), &cfg, "", g)
			if err != nil {
				t.Fatal(err)
			}
			status, _ := call(t, s, string(request), false)
			s.Close()
			if status != tc.want || len(g.calls) != tc.calls {
				t.Fatalf("status=%d calls=%d, want status=%d calls=%d; input bytes=%d", status, len(g.calls), tc.want, tc.calls, len(input))
			}
		})
	}
}

func TestContextBoundaryCountsJSONEscaping(t *testing.T) {
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	input := "say \"hello\"\\now\nnext"
	options := optionsJSON("written", "normal", "none")
	need := len([]byte(systemPrompt)) + len([]byte(userPrompt(input, options))) + 512 + cfg.Models[0].PromptOverheadTokens + outputBudget(cfg.Models[0])
	cfg.Models[0].ContextLimitTokens = need
	g := &fakeGenerator{}
	s, _ := New(context.Background(), &cfg, "", g)
	status, _ := call(t, s, `{"text":"say \"hello\"\\now\nnext","mode":"written"}`, false)
	s.Close()
	if status != 200 || len(g.calls) != 1 || g.inputs[0] != input {
		t.Fatalf("escaped boundary status=%d calls=%v inputs=%q", status, g.calls, g.inputs)
	}
	cfg.Models[0].ContextLimitTokens = need - 1
	g = &fakeGenerator{}
	s, _ = New(context.Background(), &cfg, "", g)
	defer s.Close()
	status, _ = call(t, s, `{"text":"say \"hello\"\\now\nnext","mode":"written"}`, false)
	if status != 413 || len(g.calls) != 0 {
		t.Fatalf("escaped over-boundary status=%d calls=%v", status, g.calls)
	}
}

func TestShutdownCancelsActiveTextRequest(t *testing.T) {
	cfg := testConfig()
	g := &blockingGenerator{started: make(chan struct{})}
	root, cancel := context.WithCancel(context.Background())
	s, _ := New(root, &cfg, "", g)
	done := make(chan int, 1)
	go func() { status, _ := call(t, s, `{"text":"rewrite","mode":"written"}`, false); done <- status }()
	<-g.started
	cancel()
	select {
	case status := <-done:
		if status != 503 && status != 504 {
			t.Fatalf("status=%d", status)
		}
	case <-time.After(time.Second):
		t.Fatal("request did not stop")
	}
	if !reflect.DeepEqual(g.calls, []string{"local-model"}) {
		t.Fatalf("shutdown dispatched fallback: %v", g.calls)
	}
}

func TestOllamaHTTP500ThroughGatewayUsesExistingFailureMapping(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		http.Error(w, `{"error":"synthetic runner failure"}`, http.StatusInternalServerError)
	}))
	defer server.Close()
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	cfg.Providers[0].Endpoint = server.URL
	gatewayService, err := New(context.Background(), &cfg, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer gatewayService.Close()
	status, response := call(t, gatewayService, `{"text":"synthetic input","mode":"written","model":"local-model"}`, false)
	if status != http.StatusServiceUnavailable || !strings.Contains(string(response), `"text_transform_failed"`) {
		t.Fatalf("status=%d response=%s", status, response)
	}
	if calls.Load() != 1 {
		t.Fatalf("provider calls=%d, want one without retry", calls.Load())
	}
}

func TestTotalDeadlineReturns504AndCallerCancellationDoesNotFallback(t *testing.T) {
	cfg := testConfig()
	cfg.Models = cfg.Models[:1]
	cfg.RequestTimeout = "30ms"
	g := &blockingGenerator{started: make(chan struct{})}
	s, _ := New(context.Background(), &cfg, "", g)
	status, _ := call(t, s, `{"text":"rewrite","mode":"written"}`, false)
	if status != 504 {
		t.Fatalf("total timeout status=%d", status)
	}
	s.Close()
	cfg = testConfig()
	g = &blockingGenerator{started: make(chan struct{})}
	s, _ = New(context.Background(), &cfg, "", g)
	defer s.Close()
	r := httptest.NewRequest(http.MethodPost, "/v1/text/transformations", strings.NewReader(`{"text":"rewrite","mode":"written"}`))
	r.Header.Set("Content-Type", "application/json")
	ctx, cancel := context.WithCancel(r.Context())
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()
	done := make(chan struct{})
	go func() { s.ServeHTTP(w, r); close(done) }()
	<-g.started
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("caller cancellation did not stop provider")
	}
	if !reflect.DeepEqual(g.calls, []string{"local-model"}) {
		t.Fatalf("caller cancellation dispatched fallback: %v", g.calls)
	}
}

func TestProviderTimeoutCanFallbackWithinTotalRequestDeadline(t *testing.T) {
	var localCalls, cloudCalls atomic.Int32
	local := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		localCalls.Add(1)
		select {
		case <-r.Context().Done():
		case <-time.After(200 * time.Millisecond):
		}
	}))
	defer local.Close()
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cloudCalls.Add(1)
		_, _ = w.Write([]byte(`{"choices":[{"finish_reason":"stop","message":{"content":"offline fallback"}}]}`))
	}))
	defer cloud.Close()

	cfg := testConfig()
	cfg.Providers[0].Endpoint = local.URL
	cfg.Providers[0].Timeout = "30ms"
	cfg.Providers[1].Endpoint = cloud.URL
	s, err := New(context.Background(), &cfg, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	started := time.Now()
	status, body := call(t, s, `{"text":"synthetic timeout case","mode":"written"}`, false)
	if status != http.StatusOK || time.Since(started) > time.Second || localCalls.Load() != 1 || cloudCalls.Load() != 1 {
		t.Fatalf("status=%d elapsed=%s local=%d cloud=%d body=%s", status, time.Since(started), localCalls.Load(), cloudCalls.Load(), body)
	}
	var response Response
	if err := json.Unmarshal(body, &response); err != nil {
		t.Fatal(err)
	}
	if response.Model == nil || *response.Model != "cloud-model" || !response.FallbackOccurred {
		t.Fatalf("response metadata=%#v", response)
	}
}

type blockingGenerator struct {
	started chan struct{}
	once    sync.Once
	calls   []string
}

func (b *blockingGenerator) Generate(ctx context.Context, _ config.TextProvider, m config.TextModel, _, _, _, _ string) (string, error) {
	b.calls = append(b.calls, m.ID)
	b.once.Do(func() { close(b.started) })
	<-ctx.Done()
	return "", ctx.Err()
}

func TestHTTPGeneratorOllamaSerialization(t *testing.T) {
	var got map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer secret" {
			t.Error("missing bearer")
		}
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"response":"ok","done":true,"done_reason":"stop"}`))
	}))
	defer server.Close()
	cfg := testConfig()
	p := cfg.Providers[0]
	p.Endpoint = server.URL
	m := cfg.Models[0]
	out, err := (HTTPGenerator{}).Generate(context.Background(), p, m, "secret", systemPrompt, "hello", "{}")
	if err != nil || out != "ok" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if got["keep_alive"] != float64(0) || got["stream"] != false || got["system"] != systemPrompt || strings.Contains(got["prompt"].(string), "hello") == false {
		t.Fatalf("payload %#v", got)
	}
	if think, ok := got["think"].(bool); !ok || think {
		t.Fatalf("top-level think must be explicitly false, got %#v", got["think"])
	}
	options, ok := got["options"].(map[string]any)
	if !ok {
		t.Fatalf("options has unexpected type %T", got["options"])
	}
	if _, exists := options["think"]; exists {
		t.Fatalf("think must not be nested in options: %#v", options)
	}
	for key, want := range map[string]float64{
		"num_ctx": 4096, "num_predict": 1024, "num_batch": 128,
		"num_thread": 4, "temperature": 0, "top_p": 1, "seed": 1,
	} {
		if gotValue, ok := options[key].(float64); !ok || gotValue != want {
			t.Errorf("options[%q]=%#v, want %v", key, options[key], want)
		}
	}
}
func TestHTTPGeneratorRejectsIncompleteAndClassifiesProviderFailures(t *testing.T) {
	for _, tc := range []struct {
		status   int
		body     string
		kind     FailureKind
		suppress bool
	}{{200, `{"response":"partial","done":false}`, FailureInvalidResponse, false}, {429, `{}`, FailureUnavailable, true}, {400, `{}`, FailureRejected, true}, {500, `{}`, FailureTransport, false}} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(tc.status)
			_, _ = w.Write([]byte(tc.body))
		}))
		cfg := testConfig()
		p := cfg.Providers[0]
		p.Endpoint = server.URL
		_, err := (HTTPGenerator{}).Generate(context.Background(), p, cfg.Models[0], "", systemPrompt, "x", "{}")
		server.Close()
		var pe *ProviderError
		if !errors.As(err, &pe) || pe.Kind != tc.kind || pe.Suppress != tc.suppress {
			t.Errorf("status=%d error=%#v", tc.status, err)
		}
	}
}

func TestOllamaCompletionValidation(t *testing.T) {
	tests := []struct {
		name        string
		body        string
		maxBytes    int
		want        string
		wantInvalid bool
	}{
		{
			name: "completed stop",
			body: `{"response":"final text","done":true,"done_reason":"stop"}`,
			want: "final text",
		},
		{
			name:        "token limit completion is rejected",
			body:        `{"response":"bounded text","done":true,"done_reason":"length"}`,
			wantInvalid: true,
		},
		{
			name:        "missing final text",
			body:        `{"done":true,"done_reason":"stop"}`,
			wantInvalid: true,
		},
		{
			name:        "empty final text",
			body:        `{"response":" \n ","done":true,"done_reason":"stop"}`,
			wantInvalid: true,
		},
		{
			name: "separate thinking field is ignored",
			body: `{"response":"public final","thinking":"private reasoning","done":true,"done_reason":"stop"}`,
			want: "public final",
		},
		{
			name:        "malformed JSON",
			body:        `{"response":"unfinished"`,
			wantInvalid: true,
		},
		{
			name:        "oversized response",
			body:        `{"response":"` + strings.Repeat("x", 256) + `","done":true,"done_reason":"stop"}`,
			maxBytes:    128,
			wantInvalid: true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(tc.body))
			}))
			defer server.Close()

			cfg := testConfig()
			provider := cfg.Providers[0]
			provider.Endpoint = server.URL
			generator := HTTPGenerator{MaxResponseBytes: tc.maxBytes}
			got, err := generator.Generate(context.Background(), provider, cfg.Models[0], "", systemPrompt, "synthetic", "{}")
			if tc.wantInvalid {
				var providerErr *ProviderError
				if !errors.As(err, &providerErr) || providerErr.Kind != FailureInvalidResponse {
					t.Fatalf("error=%#v, want invalid provider response", err)
				}
				if got != "" {
					t.Fatalf("returned text %q on invalid response", got)
				}
				return
			}
			if err != nil || got != tc.want {
				t.Fatalf("text=%q error=%#v, want %q", got, err, tc.want)
			}
		})
	}
}

func TestHTTPGeneratorOpenAIWireAndStructuredRefusal(t *testing.T) {
	var got map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&got)
		_, _ = w.Write([]byte(`{"choices":[{"finish_reason":"stop","message":{"content":"final text","refusal":null}}]}`))
	}))
	defer server.Close()
	cfg := testConfig()
	p := cfg.Providers[1]
	p.Endpoint = server.URL
	m := cfg.Models[1]
	m.Parameters.OpenAI.MaxCompletionTokens = nil
	budget := 1024
	m.Parameters.OpenAI.MaxTokens = &budget
	m.Parameters.OpenAI.ReasoningEffort = "none"
	out, err := (HTTPGenerator{}).Generate(context.Background(), p, m, "", systemPrompt, "user text", `{"mode":"written"}`)
	if err != nil || out != "final text" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if got["max_tokens"] != float64(1024) || got["max_completion_tokens"] != nil || got["reasoning_effort"] != "none" || got["stream"] != false {
		t.Fatalf("wire=%#v", got)
	}
	refusalServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[{"finish_reason":"stop","message":{"content":null,"refusal":"policy"}}]}`))
	}))
	defer refusalServer.Close()
	p.Endpoint = refusalServer.URL
	_, err = (HTTPGenerator{Client: refusalServer.Client()}).Generate(context.Background(), p, m, "", systemPrompt, "x", "{}")
	var pe *ProviderError
	if !errors.As(err, &pe) || pe.Kind != FailureRefused {
		t.Fatalf("refusal error=%v", err)
	}
}

func TestAcceptedGroqModelsSerializeConfiguredReasoningOptions(t *testing.T) {
	var got map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer offline-test-credential" {
			t.Error("fake provider did not receive configured test credential")
		}
		if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
			t.Errorf("decode provider request: %v", err)
		}
		_, _ = w.Write([]byte(`{"choices":[{"finish_reason":"stop","message":{"content":"synthetic fake result"}}]}`))
	}))
	defer server.Close()

	cfg, err := config.Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		id, upstream, reasoning string
	}{{"groq-qwen", "qwen/qwen3.8-27b", "none"}, {"groq-gpt-oss", "openai/gpt-oss-120b", "low"}} {
		t.Run(tc.id, func(t *testing.T) {
			var provider config.TextProvider
			var model config.TextModel
			for _, p := range cfg.TextTransform.Providers {
				if p.ID == "groq" {
					provider = p
				}
			}
			for _, m := range cfg.TextTransform.Models {
				if m.ID == tc.id {
					model = m
				}
			}
			provider.Endpoint = server.URL
			_, err := (HTTPGenerator{}).Generate(context.Background(), provider, model, "offline-test-credential", systemPrompt, "Synthetic test sentence.", `{"mode":"written"}`)
			if err != nil {
				t.Fatal(err)
			}
			if got["model"] != tc.upstream || got["stream"] != false || got["reasoning_effort"] != tc.reasoning || got["include_reasoning"] != false || got["max_completion_tokens"] != float64(1024) || got["max_tokens"] != nil {
				t.Fatalf("serialized request=%#v", got)
			}
		})
	}
}
func TestRateLimitScopeUsesBroaderConflictingSignal(t *testing.T) {
	for _, tc := range []struct {
		header, body string
		suppress     bool
	}{{"model", `{"error":{"code":"model_rate_limit"}}`, false}, {"model", `{"error":{"code":"organization_rate_limit"}}`, true}, {"provider", `{"error":{"code":"model_rate_limit"}}`, true}, {"", `{}`, true}} {
		r := &http.Response{StatusCode: 429, Header: make(http.Header)}
		if tc.header != "" {
			r.Header.Set("X-RateLimit-Scope", tc.header)
		}
		err := classifyHTTP("openai_compatible", r, []byte(tc.body))
		var pe *ProviderError
		if !errors.As(err, &pe) || pe.Suppress != tc.suppress {
			t.Errorf("header=%q body=%s error=%#v", tc.header, tc.body, err)
		}
	}
}
func ptr[T any](v T) *T { return &v }
