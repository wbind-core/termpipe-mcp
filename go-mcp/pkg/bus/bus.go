package bus

import (
	"context"
	"time"

	"github.com/kernclip/kernclip/bus/sdk/go"
)

// Artifact type constants (mirrors Antigravity metadata)
const (
	ATypeTask  = "ARTIFACT_TYPE_TASK"
	ATypePlan  = "ARTIFACT_TYPE_IMPLEMENTATION_PLAN"
	ATypeWalk  = "ARTIFACT_TYPE_WALKTHROUGH"
	ATypeOther = "ARTIFACT_TYPE_OTHER"
)

// Bus topic namespace
const (
	TopicActive      = "termpipe.workspace.active"
	TopicTask        = "termpipe.workspace.task"
	TopicInit        = "termpipe.workspace.init"
	TopicPlan        = "termpipe.workspace.plan"
	TopicWalkthrough = "termpipe.workspace.walkthrough"

	TopicReviewRequest = "termpipe.workspace.review_request"
	TopicFeedback      = "termpipe.workspace.feedback"
	TopicApproved      = "termpipe.workspace.approved"
	TopicRejected      = "termpipe.workspace.rejected"
)

// Plan status constants
const (
	PlanDraft           = "draft"
	PlanPendingApproval = "pending_approval"
	PlanApproved        = "approved"
	PlanRejected        = "rejected"
)

var ATypeToTopic = map[string]string{
	ATypeTask: TopicTask,
	ATypePlan: TopicPlan,
	ATypeWalk: TopicWalkthrough,
}

var b = kernclip_bus.New()

func Pub(topic, data string) bool {
	_, err := b.Pub(topic, data, "text/plain")
	return err == nil
}

func Get(topic string) string {
	msg, err := b.Get(topic)
	if err != nil || msg == nil {
		return ""
	}
	return msg.Data
}

// Poll blocks until any of the given topics receives a new message.
func Poll(topics []string, timeoutMs int) (string, string) {
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutMs)*time.Millisecond)
	defer cancel()

	type result struct {
		topic string
		data  string
	}
	resCh := make(chan result, 1)

	// Since Sub pattern only supports string match, we fan-out a goroutine per topic
	for _, t := range topics {
		go func(topic string) {
			_ = b.Sub(ctx, topic, func(msg kernclip_bus.Message) {
				select {
				case resCh <- result{topic: msg.Topic, data: msg.Data}:
				default:
				}
			})
		}(t)
	}

	select {
	case <-ctx.Done():
		return "", ""
	case r := <-resCh:
		return r.topic, r.data
	}
}
