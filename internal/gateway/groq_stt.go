package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"strconv"
	"strings"
	"time"

	"speech-platform/internal/transport"
)

const groqTranscriptionEndpoint = "https://api.groq.com/openai/v1/audio/transcriptions"
const groqMaxRequestBytes int64 = 25 * 1024 * 1024

type GroqSTTAdapter struct {
	apiKey   string
	model    string
	timeout  time.Duration
	endpoint string
	client   *http.Client
}

type groqSTTInput struct {
	Audio          []byte
	MediaType      string
	Language       string
	OutputLanguage string
	Timestamps     bool
}

type groqSTTFailure struct {
	Status          int
	Code            string
	Message         string
	RetryAfter      string
	CapabilityState string
}

func (e *groqSTTFailure) Error() string { return e.Message }

func selectSTTProviders(header http.Header, groqAvailable bool) ([]speechProviderID, *groqSTTFailure) {
	return selectSTTProvidersConfigured(header, true, groqAvailable, groqAvailable)
}

func selectSTTProvidersConfigured(header http.Header, localEnabled, groqEnabled, groqAvailable bool) ([]speechProviderID, *groqSTTFailure) {
	consent := false
	if values := header.Values("X-Allow-Cloud-Audio"); len(values) > 0 {
		if len(values) != 1 || (values[0] != "true" && values[0] != "false") {
			return nil, sttInputFailure(http.StatusBadRequest, "invalid_cloud_audio_consent", "X-Allow-Cloud-Audio must be true or false")
		}
		consent = values[0] == "true"
	}
	provider := header.Get("X-STT-Provider")
	if len(header.Values("X-STT-Provider")) > 1 {
		return nil, sttInputFailure(http.StatusBadRequest, "invalid_provider", "X-STT-Provider must be local or groq")
	}
	switch provider {
	case "":
		if !localEnabled && !consent && groqEnabled {
			return nil, sttInputFailure(http.StatusForbidden, "cloud_audio_not_authorized", "explicit cloud-audio authorization is required")
		}
		if !localEnabled && groqEnabled && !groqAvailable {
			return nil, sttInputFailure(http.StatusServiceUnavailable, "provider_unavailable", "selected STT provider is unavailable")
		}
		if consent && groqAvailable && !localEnabled {
			return []speechProviderID{groqWhisperProvider}, nil
		}
		if consent && groqAvailable {
			return []speechProviderID{localWhisperProvider, groqWhisperProvider}, nil
		}
		if !localEnabled {
			return nil, sttInputFailure(http.StatusServiceUnavailable, "capability_disabled", "STT capability is disabled")
		}
		return []speechProviderID{localWhisperProvider}, nil
	case "local":
		if !localEnabled {
			return nil, sttInputFailure(http.StatusServiceUnavailable, "capability_disabled", "local STT capability is disabled")
		}
		return []speechProviderID{localWhisperProvider}, nil
	case "groq":
		if !consent {
			return nil, sttInputFailure(http.StatusForbidden, "cloud_audio_not_authorized", "explicit cloud-audio authorization is required")
		}
		if !groqEnabled {
			failure := sttInputFailure(http.StatusServiceUnavailable, "provider_unavailable", "selected STT provider is unavailable")
			failure.CapabilityState = "disabled"
			return nil, failure
		}
		if !groqAvailable {
			failure := sttInputFailure(http.StatusServiceUnavailable, "provider_unavailable", "selected STT provider is unavailable")
			failure.CapabilityState = "unavailable"
			return nil, failure
		}
		return []speechProviderID{groqWhisperProvider}, nil
	default:
		return nil, sttInputFailure(http.StatusBadRequest, "invalid_provider", "X-STT-Provider must be local or groq")
	}
}

func writeGroqSTTFailure(w http.ResponseWriter, err error) {
	var failure *groqSTTFailure
	if !errors.As(err, &failure) {
		failure = &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "provider_unavailable", Message: "STT provider is unavailable"}
	}
	if failure.RetryAfter != "" {
		w.Header().Set("Retry-After", failure.RetryAfter)
	}
	if failure.CapabilityState != "" {
		w.Header().Set("X-Speech-Capability-State", failure.CapabilityState)
	}
	transport.JSON(w, failure.Status, transport.Error{Code: failure.Code, Message: failure.Message})
}

var errSTTRequestTooLarge = errors.New("STT request exceeds size limit")

func readBoundedSTTRequest(body io.Reader, contentLength, maxBytes int64) ([]byte, error) {
	if contentLength > maxBytes {
		return nil, errSTTRequestTooLarge
	}
	if contentLength >= 0 {
		buffer := make([]byte, int(contentLength))
		if _, err := io.ReadFull(body, buffer); err != nil {
			return nil, err
		}
		return buffer, nil
	}
	buffer := make([]byte, int(maxBytes)+1)
	n, err := io.ReadFull(body, buffer)
	if int64(n) > maxBytes {
		return nil, errSTTRequestTooLarge
	}
	if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
		return nil, err
	}
	return buffer[:n], nil
}

func NewGroqSTTAdapter(apiKey, model string, timeout time.Duration) (*GroqSTTAdapter, error) {
	if strings.TrimSpace(apiKey) == "" || len(apiKey) > 4096 || strings.ContainsAny(apiKey, "\r\n\t ") {
		return nil, errors.New("GROQ_STT_API_KEY is missing or malformed")
	}
	if model != "whisper-large-v3" && model != "whisper-large-v3-turbo" {
		return nil, errors.New("Groq STT model is unsupported")
	}
	if timeout <= 0 || timeout > 10*time.Minute {
		return nil, errors.New("Groq STT timeout is invalid")
	}
	return &GroqSTTAdapter{
		apiKey:   apiKey,
		model:    model,
		timeout:  timeout,
		endpoint: groqTranscriptionEndpoint,
		client: &http.Client{
			Timeout: timeout,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}, nil
}

func parseGroqSTTRequest(body []byte, contentType string) (*groqSTTInput, error) {
	mediaType, params, err := mime.ParseMediaType(contentType)
	if err != nil || mediaType != "multipart/form-data" || params["boundary"] == "" {
		return nil, sttInputFailure(http.StatusUnsupportedMediaType, "unsupported_media_type", "multipart/form-data is required")
	}
	reader := multipart.NewReader(bytes.NewReader(body), params["boundary"])
	input := &groqSTTInput{Language: "auto", OutputLanguage: "auto"}
	var languageAlias, sourceLanguage string
	seen := make(map[string]bool)
	for {
		part, nextErr := reader.NextPart()
		if nextErr == io.EOF {
			break
		}
		if nextErr != nil {
			return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "multipart request is invalid")
		}
		name := part.FormName()
		if name == "" || seen[name] {
			_ = part.Close()
			return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "multipart fields are invalid")
		}
		seen[name] = true
		switch name {
		case "audio":
			input.MediaType = strings.ToLower(strings.TrimSpace(strings.SplitN(part.Header.Get("Content-Type"), ";", 2)[0]))
			if !supportedAudioType(input.MediaType) {
				_ = part.Close()
				return nil, sttInputFailure(http.StatusUnsupportedMediaType, "unsupported_media_type", "audio media type is unsupported")
			}
			input.Audio, err = io.ReadAll(io.LimitReader(part, groqMaxRequestBytes+1))
			if err != nil || int64(len(input.Audio)) > groqMaxRequestBytes {
				_ = part.Close()
				return nil, sttInputFailure(http.StatusRequestEntityTooLarge, "request_too_large", "audio size limit exceeded")
			}
		case "language", "source_language", "output_language", "model", "timestamps", "stream":
			value, readErr := io.ReadAll(io.LimitReader(part, 8193))
			if readErr != nil || len(value) > 8192 {
				_ = part.Close()
				return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "multipart field is invalid")
			}
			text := string(value)
			switch name {
			case "language":
				languageAlias = strings.ToLower(text)
			case "source_language":
				sourceLanguage = strings.ToLower(text)
			case "output_language":
				input.OutputLanguage = strings.ToLower(text)
			case "model":
				if strings.TrimSpace(text) != "" {
					_ = part.Close()
					return nil, sttInputFailure(http.StatusBadRequest, "unsupported_model", "explicit model selection is unavailable for the selected provider")
				}
			case "timestamps":
				input.Timestamps, err = strconv.ParseBool(text)
				if err != nil {
					_ = part.Close()
					return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "timestamps must be a boolean")
				}
			case "stream":
				stream, parseErr := strconv.ParseBool(text)
				if parseErr != nil || stream {
					_ = part.Close()
					return nil, sttInputFailure(http.StatusBadRequest, "unsupported_option", "streaming is not supported")
				}
			}
		default:
			_ = part.Close()
			return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "multipart fields are invalid")
		}
		_ = part.Close()
	}
	if !seen["audio"] || len(input.Audio) == 0 {
		return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "audio is required")
	}
	if seen["language"] && seen["source_language"] && languageAlias != sourceLanguage {
		return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "language fields conflict")
	}
	if seen["source_language"] {
		input.Language = sourceLanguage
	} else if seen["language"] {
		input.Language = languageAlias
	}
	if !supportedLanguage(input.Language) || !supportedLanguage(input.OutputLanguage) {
		return nil, sttInputFailure(http.StatusBadRequest, "invalid_request", "language must be auto, ru, en, or sv")
	}
	if input.OutputLanguage != "auto" && (input.Language == "auto" || input.Language != input.OutputLanguage) {
		return nil, sttInputFailure(http.StatusBadRequest, "unsupported_translation", "the selected STT provider supports transcription only")
	}
	return input, nil
}

func (p *GroqSTTAdapter) Transcribe(ctx context.Context, input *groqSTTInput) ([]byte, string, error) {
	if p == nil || p.client == nil || input == nil {
		return nil, "", &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "provider_unavailable", Message: "STT provider is unavailable"}
	}
	if err := ctx.Err(); err != nil {
		return nil, "", groqContextFailure(err)
	}
	pipeReader, pipeWriter := io.Pipe()
	multipartWriter := multipart.NewWriter(pipeWriter)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, p.endpoint, pipeReader)
	if err != nil {
		_ = pipeReader.Close()
		_ = pipeWriter.Close()
		return nil, "", &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "provider_unavailable", Message: "STT provider is unavailable"}
	}
	request.Header.Set("Authorization", "Bearer "+p.apiKey)
	request.Header.Set("Content-Type", multipartWriter.FormDataContentType())
	writerDone := make(chan error, 1)
	go func() {
		writeErr := p.writeGroqRequest(multipartWriter, input)
		if writeErr != nil {
			_ = pipeWriter.CloseWithError(writeErr)
		} else {
			_ = pipeWriter.Close()
		}
		writerDone <- writeErr
	}()
	response, requestErr := p.client.Do(request)
	if requestErr != nil {
		_ = pipeReader.CloseWithError(requestErr)
		<-writerDone
		if ctx.Err() != nil {
			return nil, "", groqContextFailure(ctx.Err())
		}
		var networkError interface{ Timeout() bool }
		if errors.As(requestErr, &networkError) && networkError.Timeout() {
			return nil, "", &groqSTTFailure{Status: http.StatusGatewayTimeout, Code: "deadline_exceeded", Message: "speech request deadline exceeded"}
		}
		return nil, "", &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "provider_unavailable", Message: "STT provider is unavailable"}
	}
	defer response.Body.Close()
	_ = pipeReader.Close()
	writeErr := <-writerDone
	if response.StatusCode == http.StatusTooManyRequests {
		retry := retryAfter(response.Header.Get("Retry-After"))
		return nil, retry, &groqSTTFailure{Status: http.StatusTooManyRequests, Code: "overloaded", Message: "STT provider is rate limited", RetryAfter: retry}
	}
	if response.StatusCode == http.StatusRequestTimeout || response.StatusCode == http.StatusGatewayTimeout {
		return nil, "", &groqSTTFailure{Status: http.StatusGatewayTimeout, Code: "deadline_exceeded", Message: "speech request deadline exceeded"}
	}
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden || response.StatusCode >= 500 {
		return nil, "", &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "provider_unavailable", Message: "STT provider is unavailable"}
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "provider_rejected", Message: "STT provider rejected the request"}
	}
	if writeErr != nil {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an incomplete response"}
	}
	responseType, _, typeErr := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if typeErr != nil || responseType != "application/json" {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxSTTResponseBytes+1))
	if err != nil {
		if ctx.Err() != nil {
			return nil, "", groqContextFailure(ctx.Err())
		}
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	if int64(len(body)) > maxSTTResponseBytes {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	var upstream groqTranscriptionResponse
	decoder := json.NewDecoder(bytes.NewReader(body))
	if decoder.Decode(&upstream) != nil {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || (len(bytes.TrimSpace(upstream.Error)) != 0 && string(bytes.TrimSpace(upstream.Error)) != "null") || upstream.Text == nil {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	language, ok := normalizeGroqLanguage(upstream.Language)
	if !ok {
		return nil, "", &groqSTTFailure{Status: http.StatusUnprocessableEntity, Code: "unsupported_detected_language", Message: "detected audio language is unsupported"}
	}
	result := map[string]any{
		"text": *upstream.Text, "language": language, "transcription": *upstream.Text,
		"detected_language": language, "source_language": language,
		"output_language": language, "translated": false,
	}
	if input.Timestamps {
		if upstream.Segments == nil {
			return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
		}
		segments := make([]map[string]any, 0, len(upstream.Segments))
		for _, segment := range upstream.Segments {
			if segment.Start < 0 || segment.End < segment.Start || strings.TrimSpace(segment.Text) == "" {
				return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
			}
			segments = append(segments, map[string]any{"start": segment.Start, "end": segment.End, "text": segment.Text})
		}
		result["segments"] = segments
	}
	encoded, err := json.Marshal(result)
	if err != nil || int64(len(encoded)) > maxSTTResponseBytes {
		return nil, "", &groqSTTFailure{Status: http.StatusBadGateway, Code: "invalid_provider_response", Message: "STT provider returned an invalid response"}
	}
	return encoded, retryAfter(response.Header.Get("Retry-After")), nil
}

func (p *GroqSTTAdapter) writeGroqRequest(writer *multipart.Writer, input *groqSTTInput) error {
	filename := map[string]string{"audio/wav": "speech.wav", "audio/flac": "speech.flac", "audio/mpeg": "speech.mp3", "audio/ogg": "speech.ogg", "audio/mp4": "speech.m4a"}[input.MediaType]
	if filename == "" {
		return fmt.Errorf("unsupported audio type")
	}
	header := make(textproto.MIMEHeader)
	header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename="%s"`, filename))
	header.Set("Content-Type", input.MediaType)
	file, err := writer.CreatePart(header)
	if err != nil {
		return err
	}
	if _, err := file.Write(input.Audio); err != nil {
		return err
	}
	for _, field := range [][2]string{{"model", p.model}, {"response_format", "verbose_json"}} {
		key, value := field[0], field[1]
		if err := writer.WriteField(key, value); err != nil {
			return err
		}
	}
	if input.Language != "auto" {
		if err := writer.WriteField("language", input.Language); err != nil {
			return err
		}
	}
	return writer.Close()
}

type groqTranscriptionResponse struct {
	Text     *string         `json:"text"`
	Language string          `json:"language"`
	Error    json.RawMessage `json:"error"`
	Segments []struct {
		Start float64 `json:"start"`
		End   float64 `json:"end"`
		Text  string  `json:"text"`
	} `json:"segments"`
}

func sttInputFailure(status int, code, message string) *groqSTTFailure {
	return &groqSTTFailure{Status: status, Code: code, Message: message}
}

func groqContextFailure(err error) *groqSTTFailure {
	if errors.Is(err, context.DeadlineExceeded) {
		return &groqSTTFailure{Status: http.StatusGatewayTimeout, Code: "deadline_exceeded", Message: "speech request deadline exceeded"}
	}
	return &groqSTTFailure{Status: http.StatusServiceUnavailable, Code: "request_cancelled", Message: "speech request was cancelled"}
}

func supportedAudioType(value string) bool {
	switch value {
	case "audio/wav", "audio/flac", "audio/mpeg", "audio/ogg", "audio/mp4":
		return true
	default:
		return false
	}
}

func supportedLanguage(value string) bool {
	switch value {
	case "auto", "en", "ru", "sv":
		return true
	default:
		return false
	}
}

func normalizeGroqLanguage(value string) (string, bool) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "en", "english":
		return "en", true
	case "ru", "russian":
		return "ru", true
	case "sv", "swedish":
		return "sv", true
	default:
		return "", false
	}
}

func retryAfter(value string) string {
	seconds, err := strconv.Atoi(value)
	if err != nil || seconds < 1 || seconds > 3600 {
		return ""
	}
	return strconv.Itoa(seconds)
}
