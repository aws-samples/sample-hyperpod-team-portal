// Package config 从环境变量加载 controller 运行配置。
package config

import (
	"fmt"
	"os"
	"time"
)

// Config 是 controller 的全部运行参数。
type Config struct {
	// 业务集群 (集群 Y, hyperpod) 的 kubeconfig 路径。
	// ★ 必须含 exec credential (aws eks get-token), client-go 据此自动刷 EKS token
	//   (15min 过期前自动刷, 不撞 401)。informer 用此 config watch 集群 Y。
	// Pod 里由 entrypoint 用 aws eks update-kubeconfig 现生成; 本地开发指向 ~/.kube/config。
	BusinessKubeconfig string

	// 平台集群 (集群 X, controller 所在) 的 kubeconfig 路径; 留空则用 in-cluster config。
	// ★ leader election 的 lease 建在这里 (不能在业务集群 Y 放任何东西)。
	// Pod 里留空 (走 in-cluster, 用 Pod 的 SA); 本地开发指向 ~/.kube/config。
	PlatformKubeconfig string

	// DynamoDB
	DDBTable  string
	AWSRegion string
	// DryRun: 只 log 不真写 DDB (首次验证派生逻辑)。环境变量 DRY_RUN=true 开启。
	DryRun bool

	// Leader election
	EnableLeaderElection    bool
	LeaderElectionID        string
	LeaderElectionNamespace string

	// 只 watch 带此 label 的对象 (控 informer cache 内存; 留空=不过滤)。
	// 例: "platform.hyperpod.io/managed=true"
	WatchLabelSelector string

	// 健康/指标端口
	HealthProbeAddr string
	MetricsAddr     string

	// reconcile 失败重试相关
	SyncPeriod time.Duration
}

func getenv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// Load 从环境变量构建 Config; 缺必填项返回 error。
func Load() (*Config, error) {
	c := &Config{
		BusinessKubeconfig:      os.Getenv("BUSINESS_KUBECONFIG"),
		PlatformKubeconfig:      os.Getenv("PLATFORM_KUBECONFIG"),
		DDBTable:                os.Getenv("DDB_TABLE"),
		AWSRegion:               getenv("AWS_REGION", "us-west-2"),
		DryRun:                  os.Getenv("DRY_RUN") == "true",
		EnableLeaderElection:    getenv("ENABLE_LEADER_ELECTION", "true") == "true",
		LeaderElectionID:        getenv("LEADER_ELECTION_ID", "platform-controller-leader"),
		LeaderElectionNamespace: getenv("LEADER_ELECTION_NAMESPACE", "platform-system"),
		WatchLabelSelector:      os.Getenv("WATCH_LABEL_SELECTOR"),
		HealthProbeAddr:         getenv("HEALTH_PROBE_ADDR", ":8081"),
		MetricsAddr:             getenv("METRICS_ADDR", ":8080"),
		SyncPeriod:              10 * time.Hour, // informer 兜底全量 resync 周期
	}
	if c.BusinessKubeconfig == "" {
		return nil, fmt.Errorf("BUSINESS_KUBECONFIG 必填 (业务集群 kubeconfig, 含 aws eks get-token exec)")
	}
	if c.DDBTable == "" {
		return nil, fmt.Errorf("DDB_TABLE 必填")
	}
	return c, nil
}
