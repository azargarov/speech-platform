package config

import (
	"fmt"
	"gopkg.in/yaml.v3"
	"io"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	ListenHost      string `yaml:"listen_host"`
	ListenPort      int    `yaml:"listen_port"`
	MaxHeaderBytes  int    `yaml:"max_header_bytes"`
	MaxRequestBytes int64  `yaml:"max_request_bytes"`
	ReadTimeout     string `yaml:"read_timeout"`
	WriteTimeout    string `yaml:"write_timeout"`
	IdleTimeout     string `yaml:"idle_timeout"`
	ShutdownTimeout string `yaml:"shutdown_timeout"`
	STTURL          string `yaml:"stt_url"`
	APIToken        string `yaml:"api_token"`
	STTTimeout      string `yaml:"stt_timeout"`
}

const PublicMaxRequestBytes int64 = 25 * 1024 * 1024

func Load(path string) (Config, error) {
	var c Config
	f, e := os.Open(path)
	if e != nil {
		return c, e
	}
	defer f.Close()
	d := yaml.NewDecoder(f)
	d.KnownFields(true)
	if e = d.Decode(&c); e != nil {
		return c, e
	}
	var extra any
	if e = d.Decode(&extra); e != io.EOF {
		return c, fmt.Errorf("expected exactly one YAML document")
	}
	if value, ok := os.LookupEnv("SPEECH_LISTEN_PORT"); ok && value != "" {
		port, err := strconv.Atoi(value)
		if err != nil {
			return c, fmt.Errorf("SPEECH_LISTEN_PORT must be an integer")
		}
		c.ListenPort = port
	}
	if value, ok := os.LookupEnv("SPEECH_API_TOKEN"); ok && value != "" {
		c.APIToken = value
	}
	return c, c.Validate()
}
func (c Config) Validate() error {
	if !validHost(c.ListenHost) || c.ListenPort < 1 || c.ListenPort > 65535 || c.MaxRequestBytes < 1 || c.MaxRequestBytes > PublicMaxRequestBytes || c.MaxHeaderBytes < 1 {
		return fmt.Errorf("listen_host must be a hostname or IP; listen_port and max_header_bytes must be positive; max_request_bytes must be in 1..%d", PublicMaxRequestBytes)
	}
	for _, v := range []string{c.ReadTimeout, c.WriteTimeout, c.IdleTimeout, c.ShutdownTimeout} {
		d, e := time.ParseDuration(v)
		if e != nil || d <= 0 {
			return fmt.Errorf("all timeouts must be positive durations")
		}
	}
	workerURL, err := url.Parse(c.STTURL)
	if err != nil || workerURL.Scheme != "http" || workerURL.Host == "" || workerURL.User != nil || workerURL.RawQuery != "" || workerURL.Fragment != "" || workerURL.Path != "" && workerURL.Path != "/" {
		return fmt.Errorf("stt_url is required")
	}
	if c.APIToken != "" && len(c.APIToken) < 32 {
		return fmt.Errorf("SPEECH_API_TOKEN must contain at least 32 characters when configured")
	}
	sttTimeout, err := time.ParseDuration(c.STTTimeout)
	if err != nil || sttTimeout <= 0 || sttTimeout > 10*time.Minute {
		return fmt.Errorf("stt_timeout must be a positive duration no greater than 10m")
	}
	return nil
}

func validHost(host string) bool {
	if host == "" || strings.TrimSpace(host) != host || strings.ContainsAny(host, "/?#@") {
		return false
	}
	if strings.Contains(host, ":") {
		return net.ParseIP(host) != nil
	}
	if net.ParseIP(host) != nil {
		return true
	}
	if strings.Trim(host, "0123456789.") == "" {
		return false
	}
	if len(host) > 253 {
		return false
	}
	for _, label := range strings.Split(strings.TrimSuffix(host, "."), ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, r := range label {
			if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-') {
				return false
			}
		}
	}
	return true
}
