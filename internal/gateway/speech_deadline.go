package gateway

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strconv"
	"sync/atomic"
	"time"

	"speech-platform/internal/transport"
)

// Ordinary speech has one budget, including body reads and response buffering.
func speechContext(w http.ResponseWriter, r *http.Request, timeout time.Duration) (context.Context, func(), func()) {
	var ctx context.Context
	var cancel context.CancelFunc
	if timeout > 0 {
		ctx, cancel = context.WithTimeout(r.Context(), timeout)
	} else {
		ctx, cancel = context.WithCancel(r.Context())
	}
	body := r.Body // Handler may wrap r.Body after the watch is installed.
	var delivering atomic.Bool
	done := make(chan struct{})
	stop := context.AfterFunc(ctx, func() {
		defer close(done)
		// Interrupt a socket read without extending the server's existing read limit.
		controller := http.NewResponseController(w)
		_ = controller.SetReadDeadline(time.Now())
		if delivering.Load() {
			_ = controller.SetWriteDeadline(time.Now())
		}
		_ = body.Close()
	})
	beginDelivery := func() {
		delivering.Store(true)
		if ctx.Err() != nil || speechTimedOut(ctx, nil) {
			_ = http.NewResponseController(w).SetWriteDeadline(time.Now())
		}
	}
	return ctx, func() {
		if !stop() {
			<-done
		} // No late read-deadline mutation on a reused connection.
		cancel()
	}, beginDelivery
}

func speechTimedOut(ctx context.Context, err error) bool {
	deadline, bounded := ctx.Deadline()
	var timeout net.Error
	return errors.Is(ctx.Err(), context.DeadlineExceeded) || errors.Is(err, context.DeadlineExceeded) || bounded && !time.Now().Before(deadline) || errors.As(err, &timeout) && timeout.Timeout()
}

func speechStopped(w http.ResponseWriter, ctx context.Context) bool {
	if speechTimedOut(ctx, nil) {
		transport.JSON(w, http.StatusGatewayTimeout, transport.Error{Code: "deadline_exceeded", Message: "speech request deadline exceeded"})
		return true
	}
	return ctx.Err() != nil // A disconnected caller no longer needs a response.
}

func speechWorkerFailure(w http.ResponseWriter, ctx context.Context, err error) {
	if speechStopped(w, ctx) {
		return
	}
	if speechTimedOut(ctx, err) {
		transport.JSON(w, http.StatusGatewayTimeout, transport.Error{Code: "deadline_exceeded", Message: "speech request deadline exceeded"})
		return
	}
	transport.JSON(w, http.StatusServiceUnavailable, transport.Error{Code: "worker_unavailable", Message: "speech worker could not complete the request"})
}

func speechBudget(ctx context.Context) string {
	deadline, ok := ctx.Deadline()
	if !ok {
		return ""
	}
	milliseconds := time.Until(deadline).Milliseconds()
	if milliseconds < 1 {
		return ""
	}
	return strconv.FormatInt(milliseconds, 10)
}
