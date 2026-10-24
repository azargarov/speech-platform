package gateway

import (
	"context"
	"errors"
	"sort"
	"sync"
)

type speechProviderID string

const (
	defaultSpeechProvider speechProviderID = "default"
	localWhisperProvider  speechProviderID = "local-whisper"
	groqWhisperProvider   speechProviderID = "groq-whisper"
	futureGroqConcurrency                  = 2
)

var (
	ErrAdmissionClosed    = errors.New("speech admission is shutting down")
	ErrNoEligibleProvider = errors.New("no enabled provider is eligible")
)

type speechProviderConfig struct {
	capacity  int
	enabled   bool
	available bool
}

type speechProviderState struct {
	speechProviderConfig
	active int
}

type speechAdmissionWaiter struct {
	ready    chan struct{}
	eligible []speechProviderID
	provider speechProviderID
	err      error
}

// speechAdmission is a bounded in-memory queue. Each waiter carries only its
// provider eligibility and wake-up state; handlers read request bodies only
// after receiving a provider lease.
type speechAdmission struct {
	mu          sync.Mutex
	providers   map[speechProviderID]*speechProviderState
	providerIDs []speechProviderID
	waiting     []*speechAdmissionWaiter
	maxWaiting  int
	closed      bool
}

type speechAdmissionLease struct {
	provider speechProviderID
	release  func()
}

func (l *speechAdmissionLease) Release() {
	if l != nil && l.release != nil {
		l.release()
	}
}

func newSpeechAdmission(maxWaiting int) *speechAdmission {
	return newProviderSpeechAdmission(maxWaiting, map[speechProviderID]speechProviderConfig{
		defaultSpeechProvider: {capacity: 1, enabled: true, available: true},
	})
}

func newSTTAdmission(maxWaiting int) *speechAdmission {
	return newProviderSpeechAdmission(maxWaiting, map[speechProviderID]speechProviderConfig{
		localWhisperProvider: {capacity: 1, enabled: true, available: true},
		// Reserve the small internal capacity record for future integration.
		// Public requests are not eligible for Groq until cloud STT is explicitly
		// implemented and authorized.
		groqWhisperProvider: {capacity: futureGroqConcurrency, enabled: false, available: false},
	})
}

func newProviderSpeechAdmission(maxWaiting int, configured map[speechProviderID]speechProviderConfig) *speechAdmission {
	providers := make(map[speechProviderID]*speechProviderState, len(configured))
	ids := make([]speechProviderID, 0, len(configured))
	for id, cfg := range configured {
		if cfg.capacity < 1 {
			continue
		}
		providers[id] = &speechProviderState{speechProviderConfig: cfg}
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	if maxWaiting < 0 {
		maxWaiting = 0
	}
	return &speechAdmission{providers: providers, providerIDs: ids, maxWaiting: maxWaiting}
}

// acquire accepts the request's already-authorized provider set. Current STT
// routes pass only localWhisperProvider; future provider adapters must perform
// selection and cloud authorization before calling this method.
func (a *speechAdmission) acquire(ctx context.Context, eligible ...speechProviderID) (*speechAdmissionLease, bool, error) {
	if err := ctx.Err(); err != nil {
		return nil, false, err
	}
	a.mu.Lock()
	if a.closed {
		a.mu.Unlock()
		return nil, false, ErrAdmissionClosed
	}
	eligible = a.enabledEligibleLocked(eligible)
	if len(eligible) == 0 {
		a.mu.Unlock()
		return nil, false, ErrNoEligibleProvider
	}
	waiter := &speechAdmissionWaiter{ready: make(chan struct{}), eligible: eligible}
	a.waiting = append(a.waiting, waiter)
	a.dispatchLocked()
	if !waiter.granted() && len(a.waiting) > a.maxWaiting {
		a.removeWaiterLocked(waiter)
		a.mu.Unlock()
		return nil, true, nil
	}
	a.mu.Unlock()

	select {
	case <-waiter.ready:
		if waiter.err != nil {
			return nil, false, waiter.err
		}
		if err := ctx.Err(); err != nil {
			a.release(waiter.provider)
			return nil, false, err
		}
		return a.lease(waiter.provider), false, nil
	case <-ctx.Done():
		a.mu.Lock()
		if waiter.provider != "" {
			provider := waiter.provider
			a.mu.Unlock()
			a.release(provider)
			return nil, false, ctx.Err()
		}
		a.removeWaiterLocked(waiter)
		a.mu.Unlock()
		return nil, false, ctx.Err()
	}
}

func (w *speechAdmissionWaiter) granted() bool { return w.provider != "" }

func (a *speechAdmission) enabledEligibleLocked(requested []speechProviderID) []speechProviderID {
	if len(requested) == 0 {
		requested = a.providerIDs
	}
	seen := make(map[speechProviderID]struct{}, len(requested))
	eligible := make([]speechProviderID, 0, len(requested))
	for _, id := range requested {
		provider := a.providers[id]
		if provider == nil || !provider.enabled {
			continue
		}
		if _, exists := seen[id]; exists {
			continue
		}
		seen[id] = struct{}{}
		eligible = append(eligible, id)
	}
	sort.Slice(eligible, func(i, j int) bool { return eligible[i] < eligible[j] })
	return eligible
}

// setProviderAvailable applies an event-driven availability update and
// immediately promotes eligible waiters. It never probes or polls providers.
func (a *speechAdmission) setProviderAvailable(id speechProviderID, available bool) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	provider := a.providers[id]
	if provider == nil {
		return false
	}
	provider.available = available
	a.dispatchLocked()
	return true
}

func (a *speechAdmission) setProviderEnabled(id speechProviderID, enabled bool) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	provider := a.providers[id]
	if provider == nil {
		return false
	}
	provider.enabled = enabled
	if !enabled {
		for i := 0; i < len(a.waiting); {
			waiter := a.waiting[i]
			if len(a.enabledEligibleLocked(waiter.eligible)) == 0 {
				waiter.err = ErrNoEligibleProvider
				close(waiter.ready)
				copy(a.waiting[i:], a.waiting[i+1:])
				a.waiting[len(a.waiting)-1] = nil
				a.waiting = a.waiting[:len(a.waiting)-1]
				continue
			}
			i++
		}
	}
	a.dispatchLocked()
	return true
}

// shutdown rejects new acquisitions and wakes all queued requests. Active
// leases remain owned by their handlers and release normally as they finish.
func (a *speechAdmission) shutdown() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closed {
		return
	}
	a.closed = true
	for _, waiter := range a.waiting {
		waiter.err = ErrAdmissionClosed
		close(waiter.ready)
	}
	a.waiting = nil
}

func (a *speechAdmission) removeWaiterLocked(target *speechAdmissionWaiter) {
	for i, waiter := range a.waiting {
		if waiter == target {
			copy(a.waiting[i:], a.waiting[i+1:])
			a.waiting[len(a.waiting)-1] = nil
			a.waiting = a.waiting[:len(a.waiting)-1]
			return
		}
	}
}

func (a *speechAdmission) lease(id speechProviderID) *speechAdmissionLease {
	var once sync.Once
	return &speechAdmissionLease{provider: id, release: func() { once.Do(func() { a.release(id) }) }}
}

func (a *speechAdmission) release(id speechProviderID) {
	a.mu.Lock()
	defer a.mu.Unlock()
	provider := a.providers[id]
	if provider == nil || provider.active == 0 {
		return
	}
	provider.active--
	a.dispatchLocked()
}

// dispatchLocked computes a deterministic maximum matching over the bounded
// waiting list and currently free provider slots. The queue is intentionally
// small (three STT waiters), so this keeps constrained local/cloud requests
// from blocking one another without a background scheduler.
func (a *speechAdmission) dispatchLocked() {
	if a.closed || len(a.waiting) == 0 {
		return
	}
	assignment, count := a.bestAssignmentLocked()
	if count == 0 {
		return
	}
	remaining := a.waiting[:0]
	for i, waiter := range a.waiting {
		id := assignment[i]
		if id == "" {
			remaining = append(remaining, waiter)
			continue
		}
		a.providers[id].active++
		waiter.provider = id
		close(waiter.ready)
	}
	for i := len(remaining); i < len(a.waiting); i++ {
		a.waiting[i] = nil
	}
	a.waiting = remaining
}

func (a *speechAdmission) bestAssignmentLocked() ([]speechProviderID, int) {
	current := make([]speechProviderID, len(a.waiting))
	best := make([]speechProviderID, len(a.waiting))
	used := make(map[speechProviderID]int, len(a.providers))
	bestCount := -1
	var search func(int, int)
	search = func(index, count int) {
		if index == len(a.waiting) {
			if betterAssignment(current, best, count, bestCount) {
				copy(best, current)
				bestCount = count
			}
			return
		}
		waiter := a.waiting[index]
		for _, id := range waiter.eligible {
			provider := a.providers[id]
			if provider == nil || !provider.enabled || !provider.available || provider.active+used[id] >= provider.capacity {
				continue
			}
			current[index] = id
			used[id]++
			search(index+1, count+1)
			used[id]--
		}
		current[index] = ""
		search(index+1, count)
	}
	search(0, 0)
	return best, bestCount
}

func betterAssignment(candidate, best []speechProviderID, candidateCount, bestCount int) bool {
	if candidateCount != bestCount {
		return candidateCount > bestCount
	}
	for i := range candidate {
		candidateAssigned, bestAssigned := candidate[i] != "", best[i] != ""
		if candidateAssigned != bestAssigned {
			return candidateAssigned
		}
	}
	for i := range candidate {
		if candidate[i] != best[i] {
			return candidate[i] < best[i]
		}
	}
	return false
}
