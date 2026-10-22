package transport

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"strings"
)

type Error struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func ValidBearer(header, token string) bool {
	if len(header) < 8 || !strings.EqualFold(header[:7], "Bearer ") {
		return false
	}
	got := strings.TrimSpace(header[7:])
	if len(got) != len(token) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(got), []byte(token)) == 1
}

func JSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
