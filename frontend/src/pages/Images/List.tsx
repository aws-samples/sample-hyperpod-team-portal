import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { PageContainer, ProCard, ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { App, Space, Tabs, Tag } from 'antd';
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  mockImages,
  type ImageAsset,
  type ImageCategory,
  type ImageFramework,
  type ScanStatus,
} from '@/mock/assets';

const FRAMEWORK_COLOR: Record<ImageFramework, string> = {
  pytorch: 'volcano',
  tensorflow: 'orange',
  vllm: 'geekblue',
  sglang: 'cyan',
  trtllm: 'purple',
};

const SCAN_META: Record<
  ScanStatus,
  { label: string; color: string; icon: React.ReactNode }
> = {
  passed: {
    label: '通过',
    color: 'green',
    icon: <CheckCircleOutlined />,
  },
  vulnerable: {
    label: '存在漏洞',
    color: 'red',
    icon: <ExclamationCircleOutlined />,
  },
  unscanned: {
    label: '未扫描',
    color: 'default',
    icon: <MinusCircleOutlined />,
  },
};

const CATEGORY_TABS: Array<{ key: ImageCategory; label: string }> = [
  { key: 'official', label: '官方镜像' },
  { key: 'team', label: '团队镜像' },
  { key: 'personal', label: '个人镜像' },
  { key: 'community', label: '社区镜像' },
];

export default function ImagesList() {
  const { wsId = '' } = useParams();
  const { message } = App.useApp();
  const [tab, setTab] = useState<ImageCategory>('official');

  // ---- Filter: category + workspace scope ----
  // Official/community are global; team/personal filter by workspace.
  const images = useMemo(() => {
    return mockImages.filter((img) => {
      if (img.category !== tab) return false;
      if (img.category === 'official' || img.category === 'community') return true;
      return img.workspaceId === wsId;
    });
  }, [tab, wsId]);

  const columns: ProColumns<ImageAsset>[] = [
    {
      title: '镜像名',
      dataIndex: 'name',
      width: 280,
      copyable: true,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{row.name}</span>
          <span style={{ fontSize: 11, color: '#888' }}>{row.registry}</span>
        </Space>
      ),
    },
    {
      title: 'Tag',
      dataIndex: 'tag',
      width: 320,
      ellipsis: true,
      copyable: true,
      render: (v) => <code style={{ fontSize: 12 }}>{v as string}</code>,
    },
    {
      title: '框架',
      dataIndex: 'framework',
      width: 110,
      filters: true,
      valueEnum: {
        pytorch: { text: 'PyTorch' },
        tensorflow: { text: 'TensorFlow' },
        vllm: { text: 'vLLM' },
        sglang: { text: 'SGLang' },
        trtllm: { text: 'TRT-LLM' },
      },
      render: (_, row) => (
        <Tag color={FRAMEWORK_COLOR[row.framework]}>{row.framework}</Tag>
      ),
    },
    {
      title: 'CUDA',
      dataIndex: 'cudaVersion',
      width: 90,
      render: (v) => <Tag>{v as string}</Tag>,
    },
    {
      title: '基础 OS',
      dataIndex: 'baseOs',
      width: 130,
    },
    {
      title: '大小 (MB)',
      dataIndex: 'sizeMb',
      width: 110,
      search: false,
      sorter: (a, b) => a.sizeMb - b.sizeMb,
      render: (v) => (v as number).toLocaleString(),
    },
    {
      title: '扫描状态',
      dataIndex: 'scanStatus',
      width: 140,
      filters: true,
      valueEnum: {
        passed: { text: '通过' },
        vulnerable: { text: '存在漏洞' },
        unscanned: { text: '未扫描' },
      },
      render: (_, row) => {
        const meta = SCAN_META[row.scanStatus];
        if (row.scanStatus === 'vulnerable') {
          return (
            <Tag color={meta.color} icon={meta.icon}>
              {meta.label}（{row.vulnerabilities}）
            </Tag>
          );
        }
        return (
          <Tag color={meta.color} icon={meta.icon}>
            {meta.label}
          </Tag>
        );
      },
    },
    {
      title: '推送时间',
      dataIndex: 'pushedAt',
      width: 150,
      search: false,
      sorter: (a, b) =>
        dayjs(a.pushedAt).valueOf() - dayjs(b.pushedAt).valueOf(),
      render: (v) => dayjs(v as string).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      width: 220,
      search: false,
      fixed: 'right',
      render: (_, row) => (
        <Space>
          <a
            onClick={() =>
              message.success(`已复制 ${row.registry}/${row.name}:${row.tag}`)
            }
          >
            使用
          </a>
          <a onClick={() => message.info(`查看 ${row.name} Dockerfile（占位）`)}>
            Dockerfile
          </a>
          <a onClick={() => message.info(`查看 ${row.name} 扫描报告（占位）`)}>
            扫描报告
          </a>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer
      header={{
        title: '镜像中心',
        breadcrumb: {
          items: [{ title: 'Workspace' }, { title: '镜像中心' }],
        },
      }}
    >
      <ProCard bodyStyle={{ paddingTop: 0 }}>
        <Tabs
          activeKey={tab}
          onChange={(k) => setTab(k as ImageCategory)}
          items={CATEGORY_TABS.map((t) => {
            const count = mockImages.filter((img) => {
              if (img.category !== t.key) return false;
              if (img.category === 'official' || img.category === 'community')
                return true;
              return img.workspaceId === wsId;
            }).length;
            return { key: t.key, label: `${t.label}（${count}）` };
          })}
        />
        <ProTable<ImageAsset>
          rowKey="id"
          columns={columns}
          dataSource={images}
          search={{ labelWidth: 'auto' }}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          scroll={{ x: 1480 }}
          toolBarRender={false}
          options={{ reload: false, setting: true, density: true }}
        />
      </ProCard>
    </PageContainer>
  );
}
