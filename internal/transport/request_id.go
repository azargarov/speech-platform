package transport

import "context"

type requestIDKey struct{}

// WithRequestID stores the Gateway-generated ID on the request context.
func WithRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, requestIDKey{}, id)
}

// RequestID returns the request ID associated with ctx, if one is present.
func RequestID(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey{}).(string)
	return id
}
