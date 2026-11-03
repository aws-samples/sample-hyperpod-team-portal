package derive

import (
	"testing"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// mkWorkload 造一个带指定 True condition 的 Workload (测试夹具)。
func mkWorkload(trueTypes ...string) *unstructured.Unstructured {
	conds := make([]any, 0, len(trueTypes))
	for _, t := range trueTypes {
		conds = append(conds, map[string]any{"type": t, "status": "True"})
	}
	return &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "kueue.x-k8s.io/v1beta1",
		"kind":       "Workload",
		"status":     map[string]any{"conditions": conds},
	}}
}

// aggregateKueueBest: 冗余关系 (多副本互为备份, OR 语义) 的聚合 — 取最好。
// 一个副本好 = 服务可用; 进展序 PodsReady > Admitted > QuotaReserved > Queued > Evicted
// (Evicted 沉底: 被踢的副本是最差的, 不能像 kueueRank 那样排高位)。
func TestAggregateKueueBest(t *testing.T) {
	cases := []struct {
		name string
		wls  []*unstructured.Unstructured
		want string
	}{
		{"空集合→空串(冻结信号)", nil, ""},
		{"单个Admitted", []*unstructured.Unstructured{mkWorkload(KueueQuotaReserved, KueueAdmitted)}, KueueAdmitted},
		{"Admitted+Queued→取最好Admitted", []*unstructured.Unstructured{
			mkWorkload(KueueQuotaReserved, KueueAdmitted),
			mkWorkload(), // 无 True condition → Queued
		}, KueueAdmitted},
		{"PodsReady+Queued→取最好PodsReady", []*unstructured.Unstructured{
			mkWorkload(),
			mkWorkload(KueueQuotaReserved, KueueAdmitted, KueuePodsReady),
		}, KueuePodsReady},
		{"Evicted沉底: Evicted+Queued→Queued", []*unstructured.Unstructured{
			mkWorkload(KueueEvicted),
			mkWorkload(),
		}, KueueQueued},
		{"全Evicted→Evicted", []*unstructured.Unstructured{
			mkWorkload(KueueEvicted),
		}, KueueEvicted},
		{"Finished最高(理论态)", []*unstructured.Unstructured{
			mkWorkload(KueueFinished),
			mkWorkload(KueueAdmitted),
		}, KueueFinished},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := aggregateKueueBest(c.wls); got != c.want {
				t.Errorf("aggregateKueueBest() = %q, want %q", got, c.want)
			}
		})
	}
}
