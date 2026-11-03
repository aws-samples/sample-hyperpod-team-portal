import { Typography } from 'antd';
import DocPage, {
  DocSection,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsDevInstance() {
  return (
    <DocPage
      title="开发机 · 文档"
      description="云端开发环境 — 选个模板就能用, 带 GPU、预装好的 ML 环境和团队共享盘, 浏览器直接打开 Jupyter / Code Editor。"
      meta={<Text type="secondary">v3 · 2026-06-25</Text>}
    >
      <DocSection title="它是什么" subTitle="What it is" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            开发机是一台随用随开的云端开发机器, 带 GPU、预装好的 ML 开发环境 (Python、深度学习
            框架等) 和工作空间的共享数据盘。两种界面任选: <b>Jupyter</b> 或{' '}
            <b>Code Editor (VS Code)</b>。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>不用写任何配置文件 — 选资源池 (GPU / CPU) + 资源模版即可。</li>
            <li>可以用平台准备好的基础镜像, 也可以填自己的镜像地址 (如管理员开放了自定义)。</li>
            <li>支持随时停止 / 启动 — 停止后不再计费算力, 你的代码盘 (EBS) 会保留, 下次启动接着用。</li>
            <li>可挂载被授权的团队共享盘 (FSx / S3), 数据集、代码、模型直接读写。</li>
            <li>开好后, 浏览器一键打开 Jupyter / Code Editor; 也支持本地终端 / 本地 VS Code 接入。</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="怎么创建" subTitle="Create">
        <UserBlock>
          <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>左侧菜单进"开发机" → 点"新建"。</li>
            <li>填名称、显示名、描述。</li>
            <li>选界面模板: Jupyter 或 Code Editor。</li>
            <li>
              选镜像: 用<b>基础镜像</b> (平台已准备好, 开箱即用), 或选<b>自定义镜像</b>填入
              自己的镜像地址 (仅当管理员为该模板开放了自定义镜像时可选)。
            </li>
            <li>选资源池 (GPU / CPU) 和资源模版 — 模版会自动带出 GPU / CPU / 内存配置, 无需手填。</li>
            <li>设置个人代码盘 (EBS) 大小。</li>
            <li>(可选) 挂载团队共享盘: 从你被授权的 FSx / S3 目录里勾选, 可多选。</li>
            <li>(可选) 添加环境变量。</li>
            <li>提交。等状态变为运行中, 就能打开使用了。</li>
          </ol>
        </UserBlock>
      </DocSection>

      <DocSection title="怎么连接使用" subTitle="Connect">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            开发机运行起来后, 详情页有两个入口:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>"打开 Jupyter / Code Editor"</b> — 最常用。直接在浏览器新标签里打开开发界面,
              无需任何本地安装或配置, 点开就能写代码、跑 notebook。
            </li>
            <li>
              <b>"连接"</b> — 给习惯本地工具的人, 弹出三种命令行 / 本地接入方式:
              <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 4 }}>
                <li><b>终端 (SSH)</b> — 复制一行命令, 在本地终端直接进开发机</li>
                <li><b>VS Code Remote-SSH</b> — 复制配置片段, 用本地 VS Code 远程连上去</li>
                <li><b>SSM 直连</b> — 命令行进入, 适合排查问题</li>
              </ul>
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="停止 / 启动 / 删除" subTitle="Lifecycle">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>停止</b> — 不用时停掉, 释放 GPU / 算力 (不再占用配额), <b>代码盘数据保留</b>。
            </li>
            <li>
              <b>启动</b> — 在停止的开发机上重新启动, 恢复到之前的环境继续用。
            </li>
            <li>
              <b>删除</b> — 彻底回收这台开发机, 连同它的个人代码盘一起删除 (请先备份重要数据)。
              团队共享盘 (FSx / S3) 不受影响。
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="状态码 · 排查参考" subTitle="Status reference">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            列表页 / 详情页右上角的 ? 图标会展开<b>状态说明 tip</b>列出所有状态值。
            这里是排查参考的简表 (按工作流顺序):
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><b>(空)</b> → <b>Initialized</b>: CR 刚创建, Operator 还没首次 reconcile / 已接管</li>
            <li><b>Progressing</b>: Pod 创建中 / 拉镜像 / 挂 EBS / 启动 SSM agent / 初始化 IDE</li>
            <li><b>Available</b>: 终态目标, 可点"连接"或"打开 IDE"</li>
            <li><b>Stopped</b>: 主动停 / 被空闲回收, EBS 保留, 点"启动"恢复</li>
            <li><b>Degraded</b>: Pod CrashLoop / 节点失联 / EBS 挂载失败 — 看详情页"状态时间线"排查</li>
            <li><b>Queued / Error</b>: Pod 反推态 (仅详情页 sync 时出现)</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            列表页有两个独立 filter — <b>任务状态</b> (CR phase) 和<b>排队状态</b> (Kueue 六态),
            带计数, 切 chip 时显示当前命中数。
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="安全说明" subTitle="Security">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>开发机只有你本人能登录, 别人进不来。</li>
            <li>共享盘按授权挂载 — 你只能访问被授权的目录, 看不到其他团队的数据。</li>
            <li>开发机运行在内网, 不直接暴露到公网。</li>
            <li>创建 / 启动 / 停止 / 删除等操作都会留下审计记录。</li>
          </ul>
        </UserBlock>
      </DocSection>
    </DocPage>
  );
}
