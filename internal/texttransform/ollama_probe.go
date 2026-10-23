package texttransform

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"speech-platform/internal/config"
)

const ollamaNetworkAlias = "ollama"

// CheckLocalOllama verifies DNS, TCP and the read-only Ollama version endpoint
// for providers used by enabled local Ollama models. It never loads or runs a model.
func CheckLocalOllama(ctx context.Context, settings *config.TextTransform) error {
	return checkLocalOllama(ctx, settings, net.DefaultResolver.LookupIPAddr)
}

func checkLocalOllama(
	ctx context.Context,
	settings *config.TextTransform,
	lookup func(context.Context, string) ([]net.IPAddr, error),
) error {
	ctx, cancel := context.WithTimeout(ctx, 8*time.Second)
	defer cancel()
	if settings == nil || settings.Enabled == nil || !*settings.Enabled {
		return fmt.Errorf("local text transformation is not enabled")
	}
	providers := make(map[string]config.TextProvider, len(settings.Providers))
	for _, provider := range settings.Providers {
		providers[provider.ID] = provider
	}
	used := make(map[string]bool)
	for _, model := range settings.Models {
		if model.Enabled == nil || !*model.Enabled {
			continue
		}
		provider, ok := providers[model.Provider]
		if ok && provider.Type == "ollama" && provider.Locality == "local" {
			used[provider.ID] = true
		}
	}
	if len(used) == 0 {
		return fmt.Errorf("no enabled local Ollama model is configured")
	}
	for _, provider := range settings.Providers {
		if !used[provider.ID] {
			continue
		}
		if err := checkOllamaEndpoint(ctx, provider.ID, provider.Endpoint, lookup); err != nil {
			return err
		}
	}
	return nil
}

func checkOllamaEndpoint(
	ctx context.Context,
	providerID string,
	endpoint string,
	lookup func(context.Context, string) ([]net.IPAddr, error),
) error {
	parsed, err := url.Parse(endpoint)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != ollamaNetworkAlias {
		return fmt.Errorf("local Ollama provider %q must use the ollama network alias over HTTP", providerID)
	}
	port := parsed.Port()
	if port == "" {
		return fmt.Errorf("local Ollama provider %q must configure an explicit TCP port", providerID)
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return fmt.Errorf("local Ollama provider %q has an invalid TCP port", providerID)
	}
	addresses, err := lookup(ctx, parsed.Hostname())
	if err != nil || len(addresses) == 0 {
		return fmt.Errorf("local Ollama provider %q DNS lookup failed for alias %q", providerID, ollamaNetworkAlias)
	}
	address := net.JoinHostPort(addresses[0].IP.String(), port)
	dialer := &net.Dialer{Timeout: 3 * time.Second}
	connection, err := dialer.DialContext(ctx, "tcp", address)
	if err != nil {
		return fmt.Errorf("local Ollama provider %q TCP connection failed", providerID)
	}
	if err := connection.Close(); err != nil {
		return fmt.Errorf("local Ollama provider %q TCP probe cleanup failed", providerID)
	}

	versionURL := *parsed
	versionURL.Path = "/api/version"
	versionURL.RawPath = ""
	transport := &http.Transport{
		Proxy: nil,
		DialContext: func(dialCtx context.Context, network, _ string) (net.Conn, error) {
			return dialer.DialContext(dialCtx, network, address)
		},
	}
	client := &http.Client{
		Transport: transport,
		Timeout:   5 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	defer transport.CloseIdleConnections()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, versionURL.String(), nil)
	if err != nil {
		return fmt.Errorf("local Ollama provider %q version request is invalid", providerID)
	}
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("local Ollama provider %q version request failed", providerID)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("local Ollama provider %q returned HTTP %d from /api/version", providerID, response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 4097))
	if err != nil || len(body) > 4096 {
		return fmt.Errorf("local Ollama provider %q returned an invalid /api/version body", providerID)
	}
	var version struct {
		Version string `json:"version"`
	}
	if err := json.Unmarshal(body, &version); err != nil || version.Version == "" {
		return fmt.Errorf("local Ollama provider %q returned an invalid /api/version body", providerID)
	}
	return nil
}
