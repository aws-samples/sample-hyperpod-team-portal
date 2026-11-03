import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { PageContainer, StepsForm } from '@ant-design/pro-components';
import {
  ProFormDependency,
  ProFormDigit,
  ProFormRadio,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
} from '@ant-design/pro-components';
import { Alert, Card, Col, Row, Space, Tag, message } from 'antd';
import Editor from '@monaco-editor/react';
import { useAppStore } from '@/store';
import { mockWorkspaces } from '@/mock/workspaces';
import {
  mockModels,
  mockResourcePoolOptions,
} from '@/mock/assets';
import ResourcePoolPicker from '@/shared/ui/ResourcePoolPicker';
import { QuotaPreviewBar } from '@/features/quota';
import {
  aggregateQuota,
  getWorkspaceQuota,
  getWorkspaceQuotaUsage,
} from '@/features/quota/api';

type Framework = 'vllm' | 'sglang' | 'trtllm';

interface FormValues {
  // Step 1
  name: string;
  description?: string;
  resourcePoolId: string;
  modelId?: string;
  modelSource: 'fsx' | 's3' | 'hf';
  modelPath: string;
  // Step 2
  framework: Framework;
  frameworkVersion: string;
  // vLLM
  tensor_parallel_size?: number;
  pipeline_parallel_size?: number;
  max_model_len?: number;
  max_num_seqs?: number;
  dtype?: string;
  quantization?: string;
  kv_cache_dtype?: string;
  enable_prefix_caching?: boolean;
  enable_chunked_prefill?: boolean;
  gpu_memory_utilization?: number;
  // SGLang
  tp?: number;
  mem_fraction_static?: number;
  chunked_prefill_size?: number;
  schedule_policy?: string;
  // TRT-LLM
  engine_dir?: string;
  max_input_len?: number;
  max_output_len?: number;
  max_batch_size?: number;
  // Step 3
  gpuType: string;
  gpuPerReplica: number;
  replicas: number;
  maxReplicas: number;
  autoscalingMetric: 'cpu' | 'qps' | 'custom';
  // Step 4
  envVars?: string;
  exposeMode: 'cluster' | 'alb' | 'public';
  auth: 'jwt' | 'apikey' | 'none';
}

const DEFAULTS: Partial<FormValues> = {
  resourcePoolId:
    mockResourcePoolOptions[1]?.id ?? mockResourcePoolOptions[0]?.id ?? '',
  modelSource: 'fsx',
  modelPath: '/fsx/models/Qwen2-72B-Instruct',
  framework: 'vllm',
  frameworkVersion: 'vllm:0.5.3',
  tensor_parallel_size: 4,
  pipeline_parallel_size: 1,
  max_model_len: 32768,
  max_num_seqs: 256,
  dtype: 'auto',
  quantization: 'none',
  kv_cache_dtype: 'auto',
  enable_prefix_caching: true,
  enable_chunked_prefill: true,
  gpu_memory_utilization: 0.85,
  tp: 4,
  mem_fraction_static: 0.85,
  chunked_prefill_size: 8192,
  schedule_policy: 'fcfs',
  engine_dir: '/fsx/trt-engines/qwen2-72b',
  max_input_len: 4096,
  max_output_len: 2048,
  max_batch_size: 16,
  gpuType: 'H100',
  gpuPerReplica: 4,
  replicas: 1,
  maxReplicas: 4,
  autoscalingMetric: 'qps',
  exposeMode: 'cluster',
  auth: 'jwt',
};

/** Build a preview YAML snippet from current form values. */
const buildYaml = (v: Partial<FormValues>): string => {
  const engineArgs: Record<string, unknown> = {};
  if (v.framework === 'vllm') {
    engineArgs.tensor_parallel_size = v.tensor_parallel_size;
    engineArgs.pipeline_parallel_size = v.pipeline_parallel_size;
    engineArgs.max_model_len = v.max_model_len;
    engineArgs.max_num_seqs = v.max_num_seqs;
    engineArgs.dtype = v.dtype;
    engineArgs.quantization = v.quantization;
    engineArgs.kv_cache_dtype = v.kv_cache_dtype;
    engineArgs.enable_prefix_caching = v.enable_prefix_caching;
    engineArgs.enable_chunked_prefill = v.enable_chunked_prefill;
    engineArgs.gpu_memory_utilization = v.gpu_memory_utilization;
  } else if (v.framework === 'sglang') {
    engineArgs.tp = v.tp;
    engineArgs.mem_fraction_static = v.mem_fraction_static;
    engineArgs.chunked_prefill_size = v.chunked_prefill_size;
    engineArgs.schedule_policy = v.schedule_policy;
  } else if (v.framework === 'trtllm') {
    engineArgs.engine_dir = v.engine_dir;
    engineArgs.max_input_len = v.max_input_len;
    engineArgs.max_output_len = v.max_output_len;
    engineArgs.max_batch_size = v.max_batch_size;
  }
  const lines: string[] = [];
  lines.push('apiVersion: serving.hyperpod.io/v1');
  lines.push('kind: InferenceService');
  lines.push('metadata:');
  lines.push(`  name: ${v.name ?? '<name>'}`);
  lines.push('spec:');
  lines.push(`  framework: ${v.framework}`);
  lines.push(`  image: ${v.frameworkVersion}`);
  lines.push(`  model:`);
  lines.push(`    source: ${v.modelSource}`);
  lines.push(`    path: ${v.modelPath}`);
  lines.push(`  resources:`);
  lines.push(`    gpuType: ${v.gpuType}`);
  lines.push(`    gpuPerReplica: ${v.gpuPerReplica}`);
  lines.push(`  replicas: ${v.replicas}`);
  lines.push(`  autoscaling:`);
  lines.push(`    maxReplicas: ${v.maxReplicas}`);
  lines.push(`    metric: ${v.autoscalingMetric}`);
  lines.push(`  expose: ${v.exposeMode}`);
  lines.push(`  auth: ${v.auth}`);
  lines.push(`  engineArgs:`);
  Object.entries(engineArgs).forEach(([k, val]) => {
    lines.push(`    ${k}: ${JSON.stringify(val)}`);
  });
  return lines.join('\n');
};

export default function InferenceCreate() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const monacoTheme = useAppStore((s) =>
    s.themeMode === 'dark' ? 'vs-dark' : 'vs',
  );

  // Models available for this workspace; shared across dropdown + prefill.
  const wsModels = useMemo(
    () => mockModels.filter((m) => m.workspaceId === wsId),
    [wsId],
  );
  // Live quota + usage for the QuotaPreviewBar bottom bar.
  // wsUsedGpu=-1 sentinel = usage endpoint unavailable (bar shows "采集中").
  const [wsQuotaGpu, setWsQuotaGpu] = useState<number>(0);
  const [wsUsedGpu, setWsUsedGpu] = useState<number>(-1);
  useEffect(() => {
    if (!wsId) return;
    let cancelled = false;
    Promise.allSettled([
      getWorkspaceQuota(wsId),
      getWorkspaceQuotaUsage(wsId),
    ]).then(([qRes, uRes]) => {
      if (cancelled) return;
      if (qRes.status === 'fulfilled') {
        setWsQuotaGpu(aggregateQuota(qRes.value.resources).totalAccelerators);
      }
      if (uRes.status === 'fulfilled') {
        setWsUsedGpu(uRes.value.totals.accelerators);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [wsId]);

  // URL param ?model=<id> — prefill from the model catalog.
  const prefillModelId = searchParams.get('model') ?? undefined;
  const prefillModel = useMemo(
    () => mockModels.find((m) => m.id === prefillModelId),
    [prefillModelId],
  );

  const initialValues = useMemo<Partial<FormValues>>(() => {
    if (prefillModel) {
      return {
        ...DEFAULTS,
        modelId: prefillModel.id,
        modelSource: 'fsx',
        modelPath: prefillModel.fsxPath,
        name: `${prefillModel.name.toLowerCase()}-serve`,
      };
    }
    return DEFAULTS;
  }, [prefillModel]);

  const [formState, setFormState] = useState<Partial<FormValues>>(initialValues);

  const yaml = useMemo(() => buildYaml(formState), [formState]);

  const selectedPool = useMemo(
    () =>
      mockResourcePoolOptions.find((p) => p.id === formState.resourcePoolId) ??
      mockResourcePoolOptions.find((p) => p.id === DEFAULTS.resourcePoolId),
    [formState.resourcePoolId],
  );
  const requestGpu =
    (formState.gpuPerReplica ?? 0) * (formState.replicas ?? 0);
  const requestNodes = Math.max(1, Math.ceil(requestGpu / 8));

  const modelOptions = wsModels.map((m) => ({
    value: m.id,
    label: `${m.name}（${m.version} · ${m.sizeGb.toFixed(1)}GB · ${m.precision}）`,
  }));

  const handleModelSelect = (id: string, form?: unknown) => {
    const m = wsModels.find((x) => x.id === id);
    if (!m) return;
    // Mutate both formState (preview) and the StepsForm.
    setFormState((p) => ({
      ...p,
      modelId: m.id,
      modelSource: 'fsx',
      modelPath: m.fsxPath,
    }));
    const f = form as { setFieldsValue?: (v: Record<string, unknown>) => void } | undefined;
    f?.setFieldsValue?.({
      modelId: m.id,
      modelSource: 'fsx',
      modelPath: m.fsxPath,
    });
  };

  return (
    <PageContainer
      header={{
        title: '新建推理服务',
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>
                  {mockWorkspaces.find((w) => w.id === wsId)?.displayName ?? '工作空间'}
                </a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/inference`)}>推理服务</a>
              ),
            },
            { title: '新建' },
          ],
        },
      }}
    >
      <Card
        bordered={false}
        size="small"
        style={{ marginBottom: 12 }}
        bodyStyle={{ padding: 0 }}
      >
        <QuotaPreviewBar
          pool={selectedPool}
          requestGpu={requestGpu}
          requestNodes={requestNodes}
          wsQuotaGpu={wsQuotaGpu}
          wsUsedGpu={wsUsedGpu}
        />
      </Card>
      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card bordered={false}>
            <StepsForm<FormValues>
              submitter={{
                render: (props) => (
                  <Space>
                    {props.step > 0 && (
                      <a onClick={() => props.onPre?.()}>上一步</a>
                    )}
                    <a
                      onClick={() => {
                        const v = props.form?.getFieldsValue();
                        if (v) setFormState((prev) => ({ ...prev, ...v }));
                        props.onSubmit?.();
                      }}
                    >
                      {props.step === 3 ? '部署服务' : '下一步'}
                    </a>
                  </Space>
                ),
              }}
              onFinish={async (values) => {
                message.success(`服务 ${values.name} 部署请求已提交`);
                navigate(`/workspaces/${wsId}/inference`);
                return true;
              }}
              formProps={{
                validateMessages: { required: '必填项' },
              }}
            >
              <StepsForm.StepForm
                name="basic"
                title="基本信息"
                initialValues={initialValues}
                onValuesChange={(_, all) =>
                  setFormState((p) => ({ ...p, ...all }))
                }
              >
                <ProFormText
                  name="name"
                  label="服务名"
                  required
                  placeholder="qwen2-72b-prod"
                  rules={[{ required: true }]}
                />
                <ProFormTextArea
                  name="description"
                  label="描述"
                  placeholder="可选"
                />
                {prefillModel && (
                  <Alert
                    type="success"
                    showIcon
                    message={`已从模型仓库预填：${prefillModel.name} (${prefillModel.version})`}
                    style={{ marginBottom: 16 }}
                  />
                )}
                <ProFormDependency name={['modelId']}>
                  {(_, form) => (
                    <ProFormSelect
                      name="modelId"
                      label="从模型仓库选择"
                      options={modelOptions}
                      showSearch
                      placeholder="下拉选择已登记模型"
                      fieldProps={{
                        onChange: (v) =>
                          handleModelSelect(v as string, form),
                        dropdownRender: (menu: React.ReactElement) => (
                          <>
                            {menu}
                            <div
                              style={{
                                borderTop: '1px dashed #e6e6e6',
                                padding: 8,
                                textAlign: 'center',
                              }}
                            >
                              <a
                                onClick={() =>
                                  navigate(`/workspaces/${wsId}/models`)
                                }
                              >
                                + 前往模型仓库新增
                              </a>
                            </div>
                          </>
                        ),
                      }}
                    />
                  )}
                </ProFormDependency>
                <ProFormRadio.Group
                  name="modelSource"
                  label="模型源"
                  options={[
                    { label: 'FSx 路径', value: 'fsx' },
                    { label: 'S3', value: 's3' },
                    { label: 'HuggingFace Hub', value: 'hf' },
                  ]}
                />
                <ProFormText
                  name="modelPath"
                  label="模型路径"
                  required
                  rules={[{ required: true }]}
                  tooltip="从模型仓库选中后会自动填充"
                />
                <Alert
                  type="info"
                  showIcon
                  message="计算资源池"
                  style={{ marginTop: 16, marginBottom: 8 }}
                />
                <ResourcePoolPicker
                  pools={mockResourcePoolOptions}
                  value={formState.resourcePoolId}
                  onChange={(id) =>
                    setFormState((p) => ({ ...p, resourcePoolId: id }))
                  }
                />
              </StepsForm.StepForm>

              <StepsForm.StepForm
                name="engine"
                title="推理引擎"
                initialValues={DEFAULTS}
                onValuesChange={(_, all) =>
                  setFormState((p) => ({ ...p, ...all }))
                }
              >
                <ProFormRadio.Group
                  name="framework"
                  label="推理引擎"
                  radioType="button"
                  options={[
                    { label: 'vLLM', value: 'vllm' },
                    { label: 'SGLang', value: 'sglang' },
                    { label: 'TRT-LLM', value: 'trtllm' },
                  ]}
                />
                <ProFormSelect
                  name="frameworkVersion"
                  label="引擎版本"
                  options={[
                    { label: 'vllm:0.5.3', value: 'vllm:0.5.3' },
                    { label: 'vllm:0.6.0', value: 'vllm:0.6.0' },
                    { label: 'sglang:0.3.1', value: 'sglang:0.3.1' },
                    { label: 'trtllm:0.12.0', value: 'trtllm:0.12.0' },
                  ]}
                />

                <ProFormDependency name={['framework']}>
                  {({ framework }) => {
                    if (framework === 'vllm') {
                      return (
                        <Card
                          size="small"
                          title="vLLM 参数"
                          style={{ marginTop: 12 }}
                        >
                          <Row gutter={12}>
                            <Col span={12}>
                              <ProFormDigit
                                name="tensor_parallel_size"
                                label="tensor_parallel_size"
                                min={1}
                                max={16}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="pipeline_parallel_size"
                                label="pipeline_parallel_size"
                                min={1}
                                max={8}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="max_model_len"
                                label="max_model_len"
                                min={512}
                                max={1_048_576}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="max_num_seqs"
                                label="max_num_seqs"
                                min={1}
                                max={4096}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSelect
                                name="dtype"
                                label="dtype"
                                options={[
                                  { label: 'auto', value: 'auto' },
                                  { label: 'bfloat16', value: 'bfloat16' },
                                  { label: 'float16', value: 'float16' },
                                  { label: 'float8', value: 'float8' },
                                ]}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSelect
                                name="quantization"
                                label="quantization"
                                options={[
                                  { label: '无', value: 'none' },
                                  { label: 'AWQ', value: 'awq' },
                                  { label: 'GPTQ', value: 'gptq' },
                                  { label: 'FP8', value: 'fp8' },
                                ]}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSelect
                                name="kv_cache_dtype"
                                label="kv_cache_dtype"
                                options={[
                                  { label: 'auto', value: 'auto' },
                                  { label: 'fp8_e5m2', value: 'fp8_e5m2' },
                                ]}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="gpu_memory_utilization"
                                label="gpu_memory_utilization"
                                min={0.1}
                                max={0.99}
                                fieldProps={{ step: 0.05 }}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSwitch
                                name="enable_prefix_caching"
                                label="enable_prefix_caching"
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSwitch
                                name="enable_chunked_prefill"
                                label="enable_chunked_prefill"
                              />
                            </Col>
                          </Row>
                        </Card>
                      );
                    }
                    if (framework === 'sglang') {
                      return (
                        <Card
                          size="small"
                          title="SGLang 参数"
                          style={{ marginTop: 12 }}
                        >
                          <Row gutter={12}>
                            <Col span={12}>
                              <ProFormDigit name="tp" label="tp" min={1} max={16} />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="mem_fraction_static"
                                label="mem_fraction_static"
                                min={0.1}
                                max={0.99}
                                fieldProps={{ step: 0.05 }}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormDigit
                                name="chunked_prefill_size"
                                label="chunked_prefill_size"
                                min={512}
                              />
                            </Col>
                            <Col span={12}>
                              <ProFormSelect
                                name="schedule_policy"
                                label="schedule_policy"
                                options={[
                                  { label: 'FCFS', value: 'fcfs' },
                                  { label: 'LPM', value: 'lpm' },
                                  { label: 'Random', value: 'random' },
                                ]}
                              />
                            </Col>
                          </Row>
                        </Card>
                      );
                    }
                    if (framework === 'trtllm') {
                      return (
                        <Card
                          size="small"
                          title="TRT-LLM 参数"
                          style={{ marginTop: 12 }}
                        >
                          <Row gutter={12}>
                            <Col span={24}>
                              <ProFormText name="engine_dir" label="engine_dir" />
                            </Col>
                            <Col span={8}>
                              <ProFormDigit
                                name="max_input_len"
                                label="max_input_len"
                              />
                            </Col>
                            <Col span={8}>
                              <ProFormDigit
                                name="max_output_len"
                                label="max_output_len"
                              />
                            </Col>
                            <Col span={8}>
                              <ProFormDigit
                                name="max_batch_size"
                                label="max_batch_size"
                              />
                            </Col>
                          </Row>
                        </Card>
                      );
                    }
                    return null;
                  }}
                </ProFormDependency>
              </StepsForm.StepForm>

              <StepsForm.StepForm
                name="resource"
                title="资源"
                initialValues={DEFAULTS}
                onValuesChange={(_, all) =>
                  setFormState((p) => ({ ...p, ...all }))
                }
              >
                <ProFormSelect
                  name="gpuType"
                  label="GPU 类型"
                  options={[
                    { label: 'H100', value: 'H100' },
                    { label: 'A100', value: 'A100' },
                    { label: 'L40S', value: 'L40S' },
                    { label: 'g5.12xlarge (A10G x4)', value: 'g5.12xlarge' },
                  ]}
                />
                <ProFormDigit
                  name="gpuPerReplica"
                  label="每副本 GPU 数"
                  min={1}
                  max={16}
                />
                <ProFormDigit
                  name="replicas"
                  label="初始副本数"
                  min={1}
                  max={32}
                />
                <ProFormDigit
                  name="maxReplicas"
                  label="HPA 上限"
                  min={1}
                  max={64}
                />
                <ProFormRadio.Group
                  name="autoscalingMetric"
                  label="扩缩容策略"
                  options={[
                    { label: 'CPU 利用率', value: 'cpu' },
                    { label: 'QPS', value: 'qps' },
                    { label: '自定义 PromQL', value: 'custom' },
                  ]}
                />
              </StepsForm.StepForm>

              <StepsForm.StepForm
                name="advanced"
                title="高级"
                initialValues={DEFAULTS}
                onValuesChange={(_, all) =>
                  setFormState((p) => ({ ...p, ...all }))
                }
              >
                <ProFormTextArea
                  name="envVars"
                  label="环境变量"
                  placeholder={'HF_TOKEN=xxx\nCUDA_LAUNCH_BLOCKING=0'}
                  fieldProps={{ autoSize: { minRows: 4 } }}
                />
                <ProFormRadio.Group
                  name="exposeMode"
                  label="暴露方式"
                  options={[
                    { label: 'ClusterIP (内网)', value: 'cluster' },
                    { label: 'VPC Private ALB', value: 'alb' },
                    { label: '公网 (需审批)', value: 'public' },
                  ]}
                />
                <ProFormRadio.Group
                  name="auth"
                  label="鉴权"
                  options={[
                    { label: 'JWT (Cognito)', value: 'jwt' },
                    { label: 'API Key', value: 'apikey' },
                    { label: '无（仅内部测试）', value: 'none' },
                  ]}
                />
                <Alert
                  type="info"
                  showIcon
                  message="默认启用 JWT 鉴权，公网暴露强制开启鉴权。"
                />
              </StepsForm.StepForm>
            </StepsForm>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card
            size="small"
            title={
              <Space>
                <span>YAML 预览</span>
                <Tag color="blue">只读</Tag>
              </Space>
            }
            bordered={false}
            bodyStyle={{ padding: 0 }}
          >
            <Editor
              height="640px"
              defaultLanguage="yaml"
              value={yaml}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                wordWrap: 'on',
              }}
              theme={monacoTheme}
            />
          </Card>
        </Col>
      </Row>
    </PageContainer>
  );
}
