// Command controller 是 HyperPod 平台的 projection controller:
// 跨集群 watch 被管集群 (集群 Y) 的三种 CR + Kueue Workload (+可选 Pod),
// 派生状态投影到 DynamoDB。本进程跑在集群 X (不在被管集群放任何东西)。
//
// 关键跨集群配置:
//   - informer/watch: 用 BUSINESS_KUBECONFIG (指向集群 Y, 含 aws eks get-token exec →
//     client-go 自动刷 EKS 15min token, 不撞 401)
//   - leader election: 用 PLATFORM_KUBECONFIG / in-cluster (集群 X) — lease 不能放集群 Y
package main

import (
	"context"
	"os"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/selection"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	ctrllog "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"

	appcfg "gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/config"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/controller"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/ddb"
	"gitlab.aws.dev/gcr-prototyping/hyperPod-controller/services/platform-controller/internal/gvk"
)

func main() {
	ctrl.SetLogger(zap.New(zap.UseDevMode(true)))
	lg := ctrllog.Log.WithName("setup")

	cfg, err := appcfg.Load()
	if err != nil {
		lg.Error(err, "load config")
		os.Exit(1)
	}

	// ── 集群 Y (业务, watch 目标) 的 rest.Config ──
	// 从含 exec credential 的 kubeconfig 构建 → client-go 自动刷 EKS token。
	businessCfg, err := clientcmd.BuildConfigFromFlags("", cfg.BusinessKubeconfig)
	if err != nil {
		lg.Error(err, "build business (cluster Y) rest.Config")
		os.Exit(1)
	}

	// ── 集群 X (平台, leader election lease 放这) 的 rest.Config ──
	platformCfg, err := platformRestConfig(cfg.PlatformKubeconfig)
	if err != nil {
		lg.Error(err, "build platform (cluster X) rest.Config")
		os.Exit(1)
	}

	// ── DynamoDB client ──
	awsCfg, err := awsconfig.LoadDefaultConfig(context.Background(), awsconfig.WithRegion(cfg.AWSRegion))
	if err != nil {
		lg.Error(err, "load aws config")
		os.Exit(1)
	}
	writer := ddb.New(dynamodb.NewFromConfig(awsCfg), cfg.DDBTable)
	writer.DryRun = cfg.DryRun

	// ── Pod cache selector: watch Pod 但排除训练 (训练 Pod 带 HPJob label, 上百个且抖动) ──
	// 推理/开发机的 2 跳 owner 链 (Workload→Pod→CR) 两个方向都要读 Pod:
	//   - forward:  reconcile 里 CR→Pod→Workload (2 跳查关联 Workload)
	//   - reverse:  Workload 事件 → owner Pod → 读 label 反查 CR name (mapping.WorkloadToCR)
	// 二者都走 cache 才快且一致, 故必须 watch Pod。但训练 Pod 上百且频繁抖动, 全量进
	// cache 代价大 → 用 !HPJob (DoesNotExist) 把训练 Pod 挡在 cache 外。
	// 训练自己的 occupying 不受影响: 它走 podLister (API 直查, 见 setup.go)。
	podReq, err := labels.NewRequirement(gvk.LabelTrainingPodCRName, selection.DoesNotExist, nil)
	if err != nil {
		lg.Error(err, "build pod label selector")
		os.Exit(1)
	}
	podSelector := labels.NewSelector().Add(*podReq)

	// ── llm-d cache selector: LWS/Deployment 只缓存带 llmd-id 的 (平台创建的 llm-d 资源)。
	// 集群里其余 Deployment (fsx-admin / 推理后端等) 与手工建的 LWS 不进 cache,
	// informer 体积可控; 无 label 的对象本就会被 mapping.LlmdObjectToKey 过滤, 挡在
	// cache 外是纯收益。──
	llmdReq, err := labels.NewRequirement(gvk.LabelLlmdID, selection.Exists, nil)
	if err != nil {
		lg.Error(err, "build llmd label selector")
		os.Exit(1)
	}
	llmdSelector := labels.NewSelector().Add(*llmdReq)

	// ── Manager: informer 连集群 Y; leader election 连集群 X ──
	mgr, err := manager.New(businessCfg, manager.Options{
		Metrics:                metricsserver.Options{BindAddress: cfg.MetricsAddr},
		HealthProbeBindAddress: cfg.HealthProbeAddr,

		LeaderElection:          cfg.EnableLeaderElection,
		LeaderElectionID:        cfg.LeaderElectionID,
		LeaderElectionNamespace: cfg.LeaderElectionNamespace,
		// ★ 关键: lease 用集群 X (平台) 的 config (不在业务集群 Y 放 lease 对象)。
		LeaderElectionConfig:          platformCfg,
		LeaderElectionReleaseOnCancel: true,

		Cache: cache.Options{
			SyncPeriod: &cfg.SyncPeriod, // 兜底全量 resync 周期
			// Pod 只缓存非训练的 (推理/开发机 Pod); 其余类型 (CR/Workload) 不设 selector = 全缓存。
			ByObject: map[client.Object]cache.ByObject{
				&corev1.Pod{}: {Label: podSelector},
				// llm-d 双资源: ByObject 对 unstructured 按其 GVK 匹配 (apiutil.GVKForObject
				// 直接读 unstructured 声明的 GVK), 与 setup.go 里 Watches 用的 GVK 一致,
				// cache/watch 共享同一 informer。
				gvk.NewUnstructured(gvk.Deployment): {Label: llmdSelector},
				gvk.NewUnstructured(gvk.LlmdLWS):    {Label: llmdSelector},
			},
		},
	})
	if err != nil {
		lg.Error(err, "create manager")
		os.Exit(1)
	}

	// 三路 controller (训练/推理/开发机), 各 For(CR)+Watches(Workload)。
	if err := controller.SetupAll(mgr, writer); err != nil {
		lg.Error(err, "setup controllers")
		os.Exit(1)
	}

	_ = mgr.AddHealthzCheck("healthz", healthz.Ping)
	_ = mgr.AddReadyzCheck("readyz", healthz.Ping)

	lg.Info("starting controller", "ddbTable", cfg.DDBTable, "region", cfg.AWSRegion)
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		lg.Error(err, "manager exited")
		os.Exit(1)
	}
}

// platformRestConfig: 给了路径用 kubeconfig, 否则用 in-cluster (controller 跑在集群 X 内时)。
func platformRestConfig(path string) (*rest.Config, error) {
	if path != "" {
		return clientcmd.BuildConfigFromFlags("", path)
	}
	return rest.InClusterConfig()
}
