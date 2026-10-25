package config

import (
	"fmt"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

type TextTransform struct {
	Enabled               *bool          `yaml:"enabled"`
	RequestTimeout        string         `yaml:"request_timeout"`
	WarmupKeepAlive       string         `yaml:"warmup_keep_alive"`
	MaxRequestBytes       int            `yaml:"max_request_bytes"`
	MaxInputBytes         int            `yaml:"max_input_bytes"`
	MaxOutputCharacters   int            `yaml:"max_output_characters"`
	MaxResponseBytes      int            `yaml:"max_response_bytes"`
	MaxConcurrentRequests int            `yaml:"max_concurrent_requests"`
	Selection             TextSelection  `yaml:"selection"`
	Transport             TextTransport  `yaml:"transport"`
	Providers             []TextProvider `yaml:"providers"`
	Models                []TextModel    `yaml:"models"`
}
type TextSelection struct {
	Policy     string `yaml:"policy"`
	AllowCloud bool   `yaml:"allow_cloud"`
}
type TextTransport struct {
	ConnectTimeout      string `yaml:"connect_timeout"`
	TLSHandshakeTimeout string `yaml:"tls_handshake_timeout"`
	MaxIdleConnections  int    `yaml:"max_idle_connections"`
}
type TextProvider struct {
	ID        string `yaml:"id"`
	Type      string `yaml:"type"`
	Locality  string `yaml:"locality"`
	Endpoint  string `yaml:"endpoint"`
	APIKeyEnv string `yaml:"api_key_env"`
	Timeout   string `yaml:"timeout"`
}
type TextModel struct {
	ID                   string              `yaml:"id"`
	Provider             string              `yaml:"provider"`
	Model                string              `yaml:"model"`
	Enabled              *bool               `yaml:"enabled"`
	ContextLimitTokens   int                 `yaml:"context_limit_tokens"`
	PromptOverheadTokens int                 `yaml:"prompt_overhead_tokens"`
	Parameters           TextModelParameters `yaml:"parameters"`
}
type TextModelParameters struct {
	Ollama *OllamaParameters `yaml:"ollama"`
	OpenAI *OpenAIParameters `yaml:"openai_compatible"`
}
type OllamaParameters struct {
	Think       *bool    `yaml:"think"`
	KeepAlive   string   `yaml:"keep_alive"`
	NumPredict  int      `yaml:"num_predict"`
	NumBatch    int      `yaml:"num_batch"`
	NumThread   int      `yaml:"num_thread"`
	Temperature *float64 `yaml:"temperature"`
	TopP        *float64 `yaml:"top_p"`
	Seed        *int32   `yaml:"seed"`
}
type OpenAIParameters struct {
	MaxCompletionTokens *int     `yaml:"max_completion_tokens"`
	MaxTokens           *int     `yaml:"max_tokens"`
	Temperature         *float64 `yaml:"temperature"`
	TopP                *float64 `yaml:"top_p"`
	Seed                *int32   `yaml:"seed"`
	ReasoningEffort     string   `yaml:"reasoning_effort"`
	IncludeReasoning    *bool    `yaml:"include_reasoning"`
}

var textID = regexp.MustCompile(`^[a-z][a-z0-9-]{0,63}$`)
var envName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,127}$`)

func (t *TextTransform) Validate(writeTimeout string) error {
	if t == nil {
		return nil
	}
	if t.WarmupKeepAlive == "" {
		t.WarmupKeepAlive = "60s"
	}
	bad := func(s string) error { return fmt.Errorf("text_transform: %s", s) }
	if t.Enabled == nil {
		return bad("enabled is required")
	}
	requestTimeout, err := boundedDuration(t.RequestTimeout, 10*time.Minute)
	if err != nil {
		return bad("invalid request_timeout")
	}
	warmupKeepAlive, err := boundedDuration(t.WarmupKeepAlive, 24*time.Hour)
	if err != nil || warmupKeepAlive < time.Second {
		return bad("warmup_keep_alive must be from 1s to 24h")
	}
	connect, err := boundedDuration(t.Transport.ConnectTimeout, 30*time.Second)
	if err != nil {
		return bad("invalid transport.connect_timeout")
	}
	tls, err := boundedDuration(t.Transport.TLSHandshakeTimeout, 30*time.Second)
	if err != nil {
		return bad("invalid transport.tls_handshake_timeout")
	}
	if t.MaxRequestBytes < 1 || t.MaxRequestBytes > 64*1024 || t.MaxInputBytes < 1 || t.MaxInputBytes > 10000 || t.MaxOutputCharacters < 1 || t.MaxOutputCharacters > 20000 || t.MaxResponseBytes < 1 || t.MaxResponseBytes > 1024*1024 || t.MaxConcurrentRequests != 1 {
		return bad("invalid size or concurrency limit")
	}
	if t.Selection.Policy != "ordered" && t.Selection.Policy != "local_first" && t.Selection.Policy != "cloud_first" {
		return bad("selection.policy must be ordered, local_first or cloud_first")
	}
	if t.Transport.MaxIdleConnections < 1 || t.Transport.MaxIdleConnections > 16 {
		return bad("transport.max_idle_connections must be in 1..16")
	}
	serverWrite, err := time.ParseDuration(writeTimeout)
	if err != nil || requestTimeout+5*time.Second > serverWrite {
		return bad("request_timeout plus 5s must fit write_timeout")
	}
	providers := map[string]TextProvider{}
	for _, p := range t.Providers {
		if !textID.MatchString(p.ID) || providers[p.ID].ID != "" {
			return bad("provider IDs must be unique valid identifiers")
		}
		if (p.Type != "ollama" && p.Type != "openai_compatible") || (p.Locality != "local" && p.Locality != "cloud") {
			return bad("invalid provider type or locality")
		}
		u, e := url.Parse(p.Endpoint)
		if e != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return bad("provider endpoint must be an absolute HTTP(S) URL without userinfo, query or fragment")
		}
		if u.Path == "" || u.Path == "/" {
			return bad("provider endpoint must include its protocol path")
		}
		if p.Locality == "cloud" && u.Scheme != "https" {
			return bad("cloud endpoints require HTTPS")
		}
		if p.APIKeyEnv != "" && !envName.MatchString(p.APIKeyEnv) {
			return bad("api_key_env is invalid")
		}
		if p.Timeout == "" {
			return bad("provider timeout is required")
		}
		pt, e := boundedDuration(p.Timeout, 10*time.Minute)
		if e != nil || pt < connect || pt < tls || pt > requestTimeout {
			return bad("provider timeout must fit shared and request timeouts")
		}
		providers[p.ID] = p
	}
	models := map[string]bool{}
	for _, m := range t.Models {
		if !textID.MatchString(m.ID) || models[m.ID] {
			return bad("model IDs must be unique valid identifiers")
		}
		models[m.ID] = true
		if providers[m.Provider].ID == "" || strings.TrimSpace(m.Model) == "" || strings.TrimSpace(m.Model) != m.Model || len(m.Model) > 256 {
			return bad("model provider reference or model name is invalid")
		}
		if m.Enabled == nil {
			return bad("model enabled is required")
		}
		if m.ContextLimitTokens < 1 || m.ContextLimitTokens > 32768 || m.PromptOverheadTokens < 0 || m.PromptOverheadTokens >= m.ContextLimitTokens {
			return bad("model context limits are invalid")
		}
		p := providers[m.Provider]
		if p.Type == "ollama" {
			o := m.Parameters.Ollama
			if o == nil || m.Parameters.OpenAI != nil || o.NumPredict < 1 || o.NumPredict >= m.ContextLimitTokens || o.NumBatch < 1 || o.NumBatch > m.ContextLimitTokens || o.NumThread < 1 || o.NumThread > 64 {
				return bad("invalid Ollama parameters")
			}
			if o.KeepAlive != "" {
				d, e := time.ParseDuration(o.KeepAlive)
				if e != nil || d < 0 || d > 5*time.Second {
					return bad("ollama.keep_alive must be from 0s to 5s")
				}
			}
			if !validFloat(o.Temperature, 0, 2) || !validFloat(o.TopP, 0.000001, 1) {
				return bad("invalid Ollama sampling parameter")
			}
		} else {
			a := m.Parameters.OpenAI
			if a == nil || m.Parameters.Ollama != nil || (a.MaxCompletionTokens == nil) == (a.MaxTokens == nil) {
				return bad("exactly one OpenAI-compatible output budget is required")
			}
			budget := 0
			if a.MaxCompletionTokens != nil {
				budget = *a.MaxCompletionTokens
			}
			if a.MaxTokens != nil {
				budget = *a.MaxTokens
			}
			if budget < 1 || budget > 32768 || budget >= m.ContextLimitTokens {
				return bad("invalid OpenAI-compatible output budget")
			}
			if !validFloat(a.Temperature, 0, 2) || !validFloat(a.TopP, 0.000001, 1) || !validReasoning(a.ReasoningEffort) {
				return bad("invalid OpenAI-compatible parameter")
			}
		}
		budget := 0
		if m.Parameters.Ollama != nil {
			budget = m.Parameters.Ollama.NumPredict
		} else if m.Parameters.OpenAI != nil {
			if m.Parameters.OpenAI.MaxCompletionTokens != nil {
				budget = *m.Parameters.OpenAI.MaxCompletionTokens
			} else if m.Parameters.OpenAI.MaxTokens != nil {
				budget = *m.Parameters.OpenAI.MaxTokens
			}
		}
		if m.PromptOverheadTokens+budget >= m.ContextLimitTokens {
			return bad("prompt overhead and output reservation must fit model context")
		}
	}
	return nil
}

func (c Config) validateText() error { return c.TextTransform.Validate(c.WriteTimeout) }
func boundedDuration(v string, max time.Duration) (time.Duration, error) {
	d, e := time.ParseDuration(v)
	if e != nil || d <= 0 || d > max {
		return 0, fmt.Errorf("invalid duration")
	}
	return d, nil
}
func validFloat(v *float64, min, max float64) bool { return v == nil || (*v >= min && *v <= max) }
func validReasoning(v string) bool {
	if v == "" {
		return true
	}
	if len(v) > 64 {
		return false
	}
	for _, r := range v {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '_' || r == '-') {
			return false
		}
	}
	return true
}

// ResolveCredentials reads only credentials for enabled, cloud-permitted models.
func (t *TextTransform) ResolveCredentials() map[string]string {
	result := map[string]string{}
	if t == nil || t.Enabled == nil || !*t.Enabled {
		return result
	}
	providers := map[string]TextProvider{}
	for _, p := range t.Providers {
		providers[p.ID] = p
	}
	used := map[string]bool{}
	for _, m := range t.Models {
		p := providers[m.Provider]
		if m.Enabled != nil && *m.Enabled && (p.Locality == "local" || t.Selection.AllowCloud) {
			used[p.ID] = true
		}
	}
	for id := range used {
		p := providers[id]
		if p.APIKeyEnv != "" {
			result[id] = os.Getenv(p.APIKeyEnv)
		}
	}
	return result
}
