package controller

import (
	"errors"
	"testing"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"

	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

// fakeLister 模拟 discovery: groupVersion → 已注册 Kind 列表; 缺失 gv 返回 404 (同真 API server)。
type fakeLister struct {
	kinds map[string][]string
	err   error
}

func (f fakeLister) ServerResourcesForGroupVersion(gv string) (*metav1.APIResourceList, error) {
	if f.err != nil {
		return nil, f.err
	}
	kinds, ok := f.kinds[gv]
	if !ok {
		return nil, apierrors.NewNotFound(schema.GroupResource{Group: gv}, "")
	}
	list := &metav1.APIResourceList{GroupVersion: gv}
	for _, k := range kinds {
		list.APIResources = append(list.APIResources, metav1.APIResource{Kind: k})
	}
	return list, nil
}

// gvkAvailable 四分支: CRD 装了 → true; 整个 group/version 缺 (404) → false 无错;
// group/version 在但 Kind 不在 → false 无错; discovery 本身出错 (网络等) → 报错。
func TestGVKAvailable(t *testing.T) {
	d := fakeLister{kinds: map[string][]string{
		"sagemaker.amazonaws.com/v1": {"HyperPodPyTorchJob"},
		"kueue.x-k8s.io/v1beta1":     {"Workload"},
	}}

	if ok, err := gvkAvailable(d, gvk.Training); err != nil || !ok {
		t.Fatalf("Training CRD 已装应 true, 得 ok=%v err=%v", ok, err)
	}
	// Dynamo 的 nvidia.com/v1beta1 整组缺失 (本 bug 场景: 集群没装 Dynamo operator)。
	if ok, err := gvkAvailable(d, gvk.DynamoGraph); err != nil || ok {
		t.Fatalf("Dynamo CRD 缺失应 false 且无错, 得 ok=%v err=%v", ok, err)
	}
	// group/version 存在但 Kind 不存在。
	if ok, err := gvkAvailable(d, schema.GroupVersionKind{
		Group: "kueue.x-k8s.io", Version: "v1beta1", Kind: "NoSuchKind",
	}); err != nil || ok {
		t.Fatalf("Kind 缺失应 false 且无错, 得 ok=%v err=%v", ok, err)
	}
	// discovery 真错误 (非 404) 必须上抛, 不能吞成"跳过"。
	boom := errors.New("connection refused")
	if _, err := gvkAvailable(fakeLister{err: boom}, gvk.Training); !errors.Is(err, boom) {
		t.Fatalf("discovery 错误应上抛, 得 err=%v", err)
	}
}
