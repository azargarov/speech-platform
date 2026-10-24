package gateway

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

func providerTestAdmission(queueCapacity, localCapacity, cloudCapacity int, localAvailable, cloudAvailable bool) *speechAdmission {
	return newProviderSpeechAdmission(queueCapacity, map[speechProviderID]speechProviderConfig{
		localWhisperProvider: {capacity: localCapacity, enabled: true, available: localAvailable},
		groqWhisperProvider:  {capacity: cloudCapacity, enabled: true, available: cloudAvailable},
	})
}

type providerWaitResult struct {
	id    int
	lease *speechAdmissionLease
	err   error
}

func startProviderWaiter(a *speechAdmission, ctx context.Context, id int, eligible ...speechProviderID) <-chan providerWaitResult {
	done := make(chan providerWaitResult, 1)
	go func() {
		lease, full, err := a.acquire(ctx, eligible...)
		if full && err == nil {
			err = errors.New("unexpected full provider queue")
		}
		done <- providerWaitResult{id: id, lease: lease, err: err}
	}()
	return done
}

func TestProviderAdmissionSkipsIneligibleLocalWaiterForCloud(t *testing.T) {
	a := providerTestAdmission(3, 1, 2, true, true)
	localActive, full, err := a.acquire(context.Background(), localWhisperProvider)
	if err != nil || full || localActive.provider != localWhisperProvider {
		t.Fatalf("local acquisition lease=%+v full=%t err=%v", localActive, full, err)
	}

	localQueued := startProviderWaiter(a, context.Background(), 1, localWhisperProvider)
	waitForAdmissionQueue(t, a, 1)
	a.setProviderAvailable(localWhisperProvider, false)
	cloudLease, full, err := a.acquire(context.Background(), localWhisperProvider, groqWhisperProvider)
	if err != nil || full || cloudLease.provider != groqWhisperProvider {
		t.Fatalf("cloud request was blocked by local queue: lease=%+v full=%t err=%v", cloudLease, full, err)
	}
	if a.providers[localWhisperProvider].active != 1 || a.providers[groqWhisperProvider].active != 1 {
		t.Fatalf("unexpected provider activity: local=%d groq=%d", a.providers[localWhisperProvider].active, a.providers[groqWhisperProvider].active)
	}
	cloudLease.Release()
	a.setProviderAvailable(localWhisperProvider, true)
	select {
	case result := <-localQueued:
		t.Fatalf("local-only waiter used idle Groq capacity: %+v", result)
	default:
	}

	localActive.Release()
	select {
	case result := <-localQueued:
		if result.err != nil || result.lease == nil || result.lease.provider != localWhisperProvider {
			t.Fatalf("local waiter result=%+v", result)
		}
		result.lease.Release()
	case <-time.After(2 * time.Second):
		t.Fatal("local waiter was not dispatched when local capacity became available")
	}
}

func TestProviderAdmissionPreservesFIFOForCloudEligibleWaiters(t *testing.T) {
	a := providerTestAdmission(3, 1, 1, true, false)
	localActive, _, err := a.acquire(context.Background(), localWhisperProvider)
	if err != nil {
		t.Fatal(err)
	}
	olderCloud := startProviderWaiter(a, context.Background(), 1, groqWhisperProvider)
	waitForAdmissionQueue(t, a, 1)
	localOnly := startProviderWaiter(a, context.Background(), 2, localWhisperProvider)
	waitForAdmissionQueue(t, a, 2)
	newerCloud := startProviderWaiter(a, context.Background(), 3, groqWhisperProvider)
	waitForAdmissionQueue(t, a, 3)

	a.setProviderAvailable(groqWhisperProvider, true)
	first := receiveProviderWaiter(t, olderCloud, "older cloud-eligible waiter")
	if first.lease.provider != groqWhisperProvider {
		t.Fatalf("older cloud request assigned to %s", first.lease.provider)
	}
	if a.providers[groqWhisperProvider].active != 1 {
		t.Fatalf("cloud capacity exceeded: active=%d", a.providers[groqWhisperProvider].active)
	}
	first.lease.Release()
	second := receiveProviderWaiter(t, newerCloud, "newer cloud-eligible waiter")
	if second.lease.provider != groqWhisperProvider {
		t.Fatalf("newer cloud request assigned to %s", second.lease.provider)
	}
	second.lease.Release()
	select {
	case result := <-localOnly:
		t.Fatalf("local-only waiter was dispatched to Groq: %+v", result)
	default:
	}

	localActive.Release()
	local := receiveProviderWaiter(t, localOnly, "local-only waiter")
	if local.lease.provider != localWhisperProvider {
		t.Fatalf("local-only waiter assigned to %s", local.lease.provider)
	}
	local.lease.Release()
}

func TestProviderAdmissionMaximumMatchingPreservesConstrainedRequests(t *testing.T) {
	a := providerTestAdmission(3, 1, 1, false, false)
	flexible := startProviderWaiter(a, context.Background(), 0, localWhisperProvider, groqWhisperProvider)
	waitForAdmissionQueue(t, a, 1)
	localOnly := startProviderWaiter(a, context.Background(), 1, localWhisperProvider)
	waitForAdmissionQueue(t, a, 2)
	cloudOnly := startProviderWaiter(a, context.Background(), 2, groqWhisperProvider)
	waitForAdmissionQueue(t, a, 3)

	a.setProviderAvailable(groqWhisperProvider, true)
	a.setProviderAvailable(localWhisperProvider, true)
	flex := receiveProviderWaiter(t, flexible, "flexible waiter")
	local := receiveProviderWaiter(t, localOnly, "local-only waiter")
	if flex.id != 0 || local.id != 1 {
		t.Fatalf("wrong requests matched: flexible=%d local=%d", flex.id, local.id)
	}
	if flex.lease.provider != groqWhisperProvider || local.lease.provider != localWhisperProvider {
		t.Fatalf("constrained matching chose flexible=%s local=%s", flex.lease.provider, local.lease.provider)
	}
	flex.lease.Release()
	local.lease.Release()
	cloud := receiveProviderWaiter(t, cloudOnly, "cloud-only waiter")
	if cloud.lease.provider != groqWhisperProvider {
		t.Fatalf("cloud-only waiter assigned to %s", cloud.lease.provider)
	}
	cloud.lease.Release()
}

func TestProviderAdmissionCapacityAvailabilityAndDisabledSelection(t *testing.T) {
	a := providerTestAdmission(3, 1, 2, false, false)
	waiters := []<-chan providerWaitResult{
		startProviderWaiter(a, context.Background(), 0, groqWhisperProvider),
		startProviderWaiter(a, context.Background(), 1, groqWhisperProvider),
		startProviderWaiter(a, context.Background(), 2, groqWhisperProvider),
	}
	waitForAdmissionQueue(t, a, 3)
	a.setProviderAvailable(groqWhisperProvider, true)
	admitted := make([]providerWaitResult, 0, 2)
	remaining := append([]<-chan providerWaitResult(nil), waiters...)
	for len(admitted) < 2 {
		select {
		case result := <-remaining[0]:
			admitted = append(admitted, result)
			remaining[0] = nil
		case result := <-remaining[1]:
			admitted = append(admitted, result)
			remaining[1] = nil
		case result := <-remaining[2]:
			admitted = append(admitted, result)
			remaining[2] = nil
		case <-time.After(2 * time.Second):
			t.Fatal("available cloud capacity did not dispatch two waiters")
		}
	}
	if admitted[0].lease.provider != groqWhisperProvider || admitted[1].lease.provider != groqWhisperProvider || admitted[0].id == admitted[1].id || a.providers[groqWhisperProvider].active != 2 {
		t.Fatalf("cloud concurrency not enforced: admitted=%+v active=%d", admitted, a.providers[groqWhisperProvider].active)
	}
	first := admitted[0]
	first.lease.Release()
	var third providerWaitResult
	for i, channel := range remaining {
		if channel != nil {
			third = receiveProviderWaiter(t, channel, "queued cloud request")
			remaining[i] = nil
			break
		}
	}
	if third.lease.provider != groqWhisperProvider || a.providers[groqWhisperProvider].active != 2 {
		t.Fatalf("released capacity was not reused: lease=%+v active=%d", third.lease, a.providers[groqWhisperProvider].active)
	}
	admitted[1].lease.Release()
	third.lease.Release()

	disabled := newSTTAdmission(3)
	if lease, full, err := disabled.acquire(context.Background(), groqWhisperProvider); lease != nil || full || !errors.Is(err, ErrNoEligibleProvider) {
		t.Fatalf("disabled explicit provider was rerouted: lease=%+v full=%t err=%v", lease, full, err)
	}
	if disabled.providers[localWhisperProvider].active != 0 {
		t.Fatal("disabled Groq selection consumed local provider capacity")
	}
	local, full, err := disabled.acquire(context.Background(), localWhisperProvider)
	if err != nil || full || local == nil || local.provider != localWhisperProvider {
		t.Fatalf("disabled cloud provider blocked local operation: lease=%+v full=%t err=%v", local, full, err)
	}
	local.Release()
}

func TestProviderAdmissionAvailabilityUpdateAndCancellationRace(t *testing.T) {
	for iteration := 0; iteration < 50; iteration++ {
		a := providerTestAdmission(1, 1, 1, false, false)
		ctx, cancel := context.WithCancel(context.Background())
		waiter := startProviderWaiter(a, ctx, 0, localWhisperProvider)
		waitForAdmissionQueue(t, a, 1)
		start := make(chan struct{})
		var racers sync.WaitGroup
		racers.Add(2)
		go func() { defer racers.Done(); <-start; cancel() }()
		go func() { defer racers.Done(); <-start; a.setProviderAvailable(localWhisperProvider, true) }()
		close(start)
		racers.Wait()
		var result providerWaitResult
		select {
		case result = <-waiter:
		case <-time.After(2 * time.Second):
			t.Fatal("cancel/assignment race did not resolve")
		}
		if result.lease != nil {
			result.lease.Release()
		} else if !errors.Is(result.err, context.Canceled) {
			t.Fatalf("unexpected race result: %+v", result)
		}
		waitForAdmissionQueue(t, a, 0)
		if active := a.providers[localWhisperProvider].active; active != 0 {
			t.Fatalf("capacity leaked after cancel/assignment race %d: active=%d", iteration, active)
		}
		lease, full, err := a.acquire(context.Background(), localWhisperProvider)
		if err != nil || full || lease == nil {
			t.Fatalf("provider did not recover after race %d: lease=%v full=%t err=%v", iteration, lease != nil, full, err)
		}
		lease.Release()
		cancel()
	}
}

func TestProviderAdmissionShutdownWakesWaitersAndRejectsNewWork(t *testing.T) {
	a := providerTestAdmission(3, 1, 1, true, true)
	active, _, err := a.acquire(context.Background(), localWhisperProvider)
	if err != nil {
		t.Fatal(err)
	}
	waiter := startProviderWaiter(a, context.Background(), 0, localWhisperProvider)
	waitForAdmissionQueue(t, a, 1)
	a.shutdown()
	var result providerWaitResult
	select {
	case result = <-waiter:
	case <-time.After(2 * time.Second):
		t.Fatal("shutdown did not wake waiter")
	}
	if !errors.Is(result.err, ErrAdmissionClosed) || result.lease != nil {
		t.Fatalf("shutdown waiter result=%+v", result)
	}
	if lease, full, err := a.acquire(context.Background(), localWhisperProvider); lease != nil || full || !errors.Is(err, ErrAdmissionClosed) {
		t.Fatalf("shutdown accepted new work: lease=%+v full=%t err=%v", lease, full, err)
	}
	active.Release()
	if a.providers[localWhisperProvider].active != 0 {
		t.Fatalf("active lease was not released: %d", a.providers[localWhisperProvider].active)
	}
}

func receiveProviderWaiter(t *testing.T, result <-chan providerWaitResult, name string) providerWaitResult {
	t.Helper()
	select {
	case got := <-result:
		if got.err != nil || got.lease == nil {
			t.Fatalf("%s result=%+v", name, got)
		}
		return got
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s", name)
		return providerWaitResult{}
	}
}
