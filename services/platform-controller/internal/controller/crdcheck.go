package controller

import (
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// gvResourceLister 是 discovery.DiscoveryInterface 中本文件用到的最小子集
// (真实现 = discovery client; 测试用 fake)。
type gvResourceLister interface {
	ServerResourcesForGroupVersion(groupVersion string) (*metav1.APIResourceList, error)
}

// gvkAvailable 查业务集群是否装了 g 对应的 CRD (API server discovery)。
// 缺失 (整个 group/version 404, 或 gv 在但 Kind 不在) → (false, nil): 调用方跳过该路,
// 不算错误 — 例如集群没装 NVIDIA Dynamo operator 时 nvidia.com/v1beta1 整组不存在。
// discovery 本身失败 (网络/权限) → 上抛: 不能吞成"跳过", 否则抖动会静默丢一路 controller。
func gvkAvailable(d gvResourceLister, g schema.GroupVersionKind) (bool, error) {
	list, err := d.ServerResourcesForGroupVersion(g.GroupVersion().String())
	if apierrors.IsNotFound(err) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	for _, r := range list.APIResources {
		if r.Kind == g.Kind {
			return true, nil
		}
	}
	return false, nil
}
