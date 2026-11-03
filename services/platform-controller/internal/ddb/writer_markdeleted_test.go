package ddb

import (
	"strings"
	"testing"

	ddbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

func TestBuildMarkDeleted_KeepPhase(t *testing.T) {
	// RayJob: keepPhase=true → 不写 phase。
	upd, cond, names, values := buildMarkDeleted(true)
	if strings.Contains(upd, "#phase") {
		t.Errorf("keepPhase=true 不应含 phase, got update=%q", upd)
	}
	if _, ok := names["#phase"]; ok {
		t.Errorf("keepPhase=true names 不应含 #phase")
	}
	if _, ok := values[":phase"]; ok {
		t.Errorf("keepPhase=true values 不应含 :phase")
	}
	if !strings.Contains(upd, "REMOVE active_ws") {
		t.Errorf("必须 REMOVE active_ws, got %q", upd)
	}
	if !strings.Contains(upd, "#md.#ks = :finished") {
		t.Errorf("必须 SET ks=Finished, got %q", upd)
	}
	// RayJob 停止 (删 CR, KubeRay 没写 endTime): 补 ended_at = if_not_exists(ended_at, now),
	// 否则前端运行时长在 stop 后继续往上涨。正常跑完已有真实 endTime 则 if_not_exists 保留。
	if !strings.Contains(upd, "if_not_exists(#md.#ended_at, :now)") {
		t.Errorf("keepPhase=true 应补 ended_at (if_not_exists), got %q", upd)
	}
	if _, ok := values[":now"]; !ok {
		t.Errorf("keepPhase=true 应有 :now 值补 ended_at")
	}
	if names["#ended_at"] != "ended_at" {
		t.Errorf("names[#ended_at] = %q, want ended_at", names["#ended_at"])
	}
	if cond != "attribute_exists(workspace_id)" {
		t.Errorf("cond = %q, want attribute_exists(workspace_id)", cond)
	}
}

func TestBuildMarkDeleted_DefaultPhaseStopped(t *testing.T) {
	// 训练等: keepPhase=false → 写 phase=Stopped。
	upd, _, names, values := buildMarkDeleted(false)
	if !strings.Contains(upd, "#md.#phase = :phase") {
		t.Errorf("keepPhase=false 应 SET phase, got %q", upd)
	}
	if names["#phase"] != "phase" {
		t.Errorf("names[#phase] = %q, want phase", names["#phase"])
	}
	if !strings.Contains(upd, "REMOVE active_ws") {
		t.Errorf("必须 REMOVE active_ws, got %q", upd)
	}
	ph, ok := values[":phase"].(*ddbtypes.AttributeValueMemberS)
	if !ok || ph.Value != "Stopped" {
		t.Errorf("values[:phase] = %v, want S \"Stopped\"", values[":phase"])
	}
}
