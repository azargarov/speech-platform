package gateway

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"speech-platform/internal/transport"
)

const RequestIDHeader = "X-Request-ID"
const maxLoggedErrorBody = 4096

// WithRequestID assigns a fresh Gateway-owned ID to every HTTP request.
// Incoming IDs are deliberately replaced so callers cannot spoof log correlation.
func WithRequestID(next http.Handler, logger *slog.Logger) http.Handler {
	if logger == nil {
		logger = slog.Default()
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, err := newRequestID()
		if err != nil {
			logger.Error("request ID generation failed")
			transport.JSON(w, http.StatusInternalServerError, transport.Error{Code: "internal_error", Message: "request could not be processed"})
			return
		}
		w.Header().Set(RequestIDHeader, id)
		r = r.WithContext(transport.WithRequestID(r.Context(), id))
		started := time.Now()
		logger.Info("request started", "request_id", id, "method", r.Method, "path", r.URL.Path)
		recorded := &requestLogWriter{ResponseWriter: w}
		defer func() {
			status := recorded.status
			if status == 0 {
				status = http.StatusOK
			}
			attrs := []any{
				"request_id", id,
				"method", r.Method,
				"path", r.URL.Path,
				"status", status,
				"elapsed_ms", time.Since(started).Milliseconds(),
			}
			if provider := recorded.Header().Get("X-Speech-Provider"); provider != "" {
				attrs = append(attrs, "provider", provider)
			}
			if fingerprint := recorded.Header().Get("X-Speech-Prompt-SHA256"); fingerprint != "" {
				attrs = append(attrs, "prompt_sha256", fingerprint)
			}
			if status >= 400 {
				if code := apiErrorCode(recorded.errorBody); code != "" {
					attrs = append(attrs, "api_code", code)
				}
				logger.Warn("request failed", attrs...)
				return
			}
			logger.Info("request completed", attrs...)
		}()
		next.ServeHTTP(recorded, r)
	})
}

func newRequestID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	encoded := hex.EncodeToString(value[:])
	return fmt.Sprintf("%s-%s-%s-%s-%s", encoded[:8], encoded[8:12], encoded[12:16], encoded[16:20], encoded[20:]), nil
}

type requestLogWriter struct {
	http.ResponseWriter
	status    int
	errorBody []byte
}

func (w *requestLogWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (w *requestLogWriter) WriteHeader(status int) {
	if w.status != 0 {
		return
	}
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}

func (w *requestLogWriter) Write(body []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	if w.status >= 400 && len(w.errorBody) < maxLoggedErrorBody {
		remaining := maxLoggedErrorBody - len(w.errorBody)
		captured := body
		if len(captured) > remaining {
			captured = captured[:remaining]
		}
		w.errorBody = append(w.errorBody, captured...)
	}
	return w.ResponseWriter.Write(body)
}

func apiErrorCode(body []byte) string {
	var payload struct {
		Code string `json:"code"`
	}
	if len(body) == 0 || json.Unmarshal(body, &payload) != nil || len(payload.Code) > 64 {
		return ""
	}
	for _, char := range payload.Code {
		if (char < 'a' || char > 'z') && (char < '0' || char > '9') && char != '_' {
			return ""
		}
	}
	return payload.Code
}
