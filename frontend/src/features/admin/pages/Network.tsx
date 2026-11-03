import {
  Badge,
  Card,
  Col,
  Descriptions,
  Progress,
  Row,
  Space,
  Table,
  Tag,
  Typography,
  theme,
} from 'antd';
import { PageContainer } from '@ant-design/pro-components';
import {
  ApiOutlined,
  CloudOutlined,
  GlobalOutlined,
  PartitionOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { mockNetworkInfo } from '@/mock/infra';

const { Text } = Typography;

export default function AdminNetwork() {
  const { token } = theme.useToken();
  const net = mockNetworkInfo;

  return (
    <PageContainer
      title="网络拓扑"
      subTitle="VPC / 子网 / Security Group / VPC Endpoint / NAT Gateway"
    >
      {/* VPC overview */}
      <Card
        title={
          <Space>
            <GlobalOutlined />
            VPC 基本信息
          </Space>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
      >
        <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small">
          <Descriptions.Item label="VPC ID">
            <Text code>{net.vpc.id}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="CIDR">
            <Tag color="geekblue">{net.vpc.cidr}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Region">
            <Tag color="blue">{net.vpc.region}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {dayjs(net.vpc.createdAt).format('YYYY-MM-DD HH:mm')}
          </Descriptions.Item>
          <Descriptions.Item label="DNS Support">
            <Badge
              status={net.vpc.dnsSupport ? 'success' : 'default'}
              text={net.vpc.dnsSupport ? 'Enabled' : 'Disabled'}
            />
          </Descriptions.Item>
          <Descriptions.Item label="DNS Hostnames">
            <Badge
              status={net.vpc.dnsHostnames ? 'success' : 'default'}
              text={net.vpc.dnsHostnames ? 'Enabled' : 'Disabled'}
            />
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Subnets */}
      <Card
        title={
          <Space>
            <PartitionOutlined />
            子网列表 ({net.subnets.length})
          </Space>
        }
        style={{ borderRadius: 12, marginBottom: 16 }}
      >
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={net.subnets}
          columns={[
            {
              title: '子网 ID',
              dataIndex: 'id',
              render: (v: string) => <Text code>{v}</Text>,
            },
            {
              title: 'CIDR',
              dataIndex: 'cidr',
              render: (v: string) => <Tag color="geekblue">{v}</Tag>,
            },
            { title: 'AZ', dataIndex: 'az' },
            {
              title: '类型',
              dataIndex: 'type',
              render: (v: string) => (
                <Tag color={v === 'Public' ? 'green' : 'purple'}>{v}</Tag>
              ),
            },
            {
              title: 'IP 容量',
              width: 220,
              render: (_: unknown, row) => {
                const used = row.totalIps - row.availableIps;
                const pct = Math.round((used / row.totalIps) * 100);
                return (
                  <Space direction="vertical" size={0} style={{ width: '100%' }}>
                    <Text style={{ fontSize: 12 }}>
                      可用 {row.availableIps} / {row.totalIps}
                    </Text>
                    <Progress
                      percent={pct}
                      size="small"
                      showInfo={false}
                      strokeColor={
                        pct > 80
                          ? token.colorError
                          : pct > 50
                          ? token.colorWarning
                          : token.colorPrimary
                      }
                    />
                  </Space>
                );
              },
            },
          ]}
        />
      </Card>

      {/* SG + NAT Gateway */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} xl={14}>
          <Card
            title={
              <Space>
                <SafetyCertificateOutlined />
                Security Groups ({net.securityGroups.length})
              </Space>
            }
            style={{ borderRadius: 12, height: '100%' }}
          >
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              {net.securityGroups.map((sg) => (
                <div
                  key={sg.id}
                  style={{
                    padding: 12,
                    borderRadius: 8,
                    background: token.colorFillQuaternary,
                    border: `1px solid ${token.colorBorderSecondary}`,
                  }}
                >
                  <Space
                    style={{ width: '100%', justifyContent: 'space-between' }}
                  >
                    <Space>
                      <Text strong>{sg.name}</Text>
                      <Text code style={{ fontSize: 11 }}>
                        {sg.id}
                      </Text>
                    </Space>
                    <Tag>{sg.rules.length} 条规则</Tag>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                    {sg.description}
                  </Text>
                  <Space size={4} wrap style={{ marginTop: 6 }}>
                    {sg.rules.slice(0, 4).map((r, i) => (
                      <Tag
                        key={i}
                        color={r.direction === 'Ingress' ? 'blue' : 'orange'}
                        style={{ fontSize: 11 }}
                      >
                        {r.direction}: {r.protocol}/
                        {r.fromPort === r.toPort
                          ? r.fromPort
                          : `${r.fromPort}-${r.toPort}`}{' '}
                        ← {r.source}
                      </Tag>
                    ))}
                    {sg.rules.length > 4 && (
                      <Tag>+{sg.rules.length - 4} 条</Tag>
                    )}
                  </Space>
                </div>
              ))}
            </Space>
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card
            title={
              <Space>
                <CloudOutlined />
                NAT Gateways ({net.natGateways.length})
              </Space>
            }
            style={{ borderRadius: 12, height: '100%' }}
          >
            <Table
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={net.natGateways}
              columns={[
                {
                  title: 'ID',
                  dataIndex: 'id',
                  render: (v: string) => <Text code>{v}</Text>,
                },
                {
                  title: '子网',
                  dataIndex: 'subnetId',
                  render: (v: string) => <Tag>{v}</Tag>,
                },
                {
                  title: 'EIP',
                  dataIndex: 'elasticIp',
                  render: (v: string) => <Text code>{v}</Text>,
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  render: (v: string) => (
                    <Badge
                      status={v === 'available' ? 'success' : 'processing'}
                      text={v}
                    />
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* VPC endpoints */}
      <Card
        title={
          <Space>
            <ApiOutlined />
            VPC Endpoints ({net.endpoints.length})
          </Space>
        }
        style={{ borderRadius: 12 }}
      >
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={net.endpoints}
          columns={[
            {
              title: 'Endpoint ID',
              dataIndex: 'id',
              width: 120,
              render: (v: string) => <Text code>{v}</Text>,
            },
            {
              title: 'Service',
              dataIndex: 'serviceName',
              render: (v: string) => {
                const short = v.split('.').slice(-2).join('.');
                return (
                  <Space direction="vertical" size={0}>
                    <Text strong style={{ fontSize: 12 }}>
                      {short}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {v}
                    </Text>
                  </Space>
                );
              },
            },
            {
              title: '类型',
              dataIndex: 'type',
              width: 110,
              render: (v: string) => (
                <Tag color={v === 'Gateway' ? 'green' : 'blue'}>{v}</Tag>
              ),
            },
            {
              title: 'AZ',
              dataIndex: 'az',
              render: (v: string[]) =>
                v.map((a) => (
                  <Tag key={a} style={{ marginInlineEnd: 4 }}>
                    {a}
                  </Tag>
                )),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 120,
              render: (v: string) => (
                <Badge
                  status={v === 'available' ? 'success' : 'warning'}
                  text={v}
                />
              ),
            },
          ]}
        />
      </Card>
    </PageContainer>
  );
}
