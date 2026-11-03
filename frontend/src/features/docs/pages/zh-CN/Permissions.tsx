import { Typography } from 'antd';
import DocPage, { DocSection, KeyValueList } from '../../components/DocPage';

const { Paragraph, Text } = Typography;

/**
 * 关于权限 — 面向最终用户的权限说明 (不讲实现, 只回答"我能做什么 / 为什么按钮没了")。
 *
 * 写作约束:
 *   - 不出现 DDB 表 / gate 函数名 / 401 / 403 / JWT 这类工程术语
 *   - 全篇只用 UserBlock 风格 (DocSection 默认排版), 不用 TechBlock
 *   - 速查表用 KeyValueList, "动作 → 谁能做"两列, 最直观
 */
export default function DocsPermissions() {
  return (
    <DocPage
      title="关于权限 · 文档"
      description="平台只有三种身份 — 看完这页就能回答「我能做什么、为什么我看不见某个按钮、找谁帮我做」。"
      meta={<Text type="secondary">v2 · 2026-06-25</Text>}
    >
      <DocSection title="你是哪种身份" subTitle="Who am I" marginTop={0}>
        <Paragraph style={{ marginBottom: 12 }}>
          平台不分细粒度角色, 只有三种身份, 按"管的事大不大"由大到小:
        </Paragraph>
        <KeyValueList
          items={[
            {
              k: '平台管理员',
              v: (
                <>
                  管整个平台 — 建工作空间、调平台级开关。
                  数量很少, 通常是平台运维同事。
                </>
              ),
            },
            {
              k: '工作空间管理员',
              v: (
                <>
                  管<b>某一个</b>工作空间 — 拉成员、配存储、给挂载授权、看本团队所有任务、调任务优先级。
                  你可能在 A 空间是管理员, 在 B 空间只是普通成员。
                </>
              ),
            },
            {
              k: '普通成员',
              v: (
                <>
                  在所属工作空间里跑<b>自己的</b>开发机 / 训练 / 推理。
                  只能看到自己的任务, 看不到别人的。
                </>
              ),
            },
          ]}
        />
        <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          想知道自己当前是哪种身份: 看左上角头像的下拉, 或者看左侧菜单 — 有没有"管理中心"
          就是最直接的判断 (普通成员看不到这一栏)。
        </Paragraph>
      </DocSection>

      <DocSection title="谁能做什么" subTitle="Capability">
        <Paragraph style={{ marginBottom: 12 }}>
          下面是常见动作的速查表 — 列里的"谁"就是能做这件事的人, 其他人在界面上看不到这个按钮。
        </Paragraph>
        <KeyValueList
          items={[
            { k: '新建工作空间', v: <>仅<b>平台管理员</b></> },
            { k: '删除工作空间', v: <>仅<b>平台管理员</b></> },
            { k: '加 / 移成员', v: <>仅<b>平台管理员</b></> },
            {
              k: '挂 FSx / S3 存储',
              v: <><b>平台管理员</b> 或 <b>工作空间管理员</b></>,
            },
            {
              k: '给成员授权使用某块挂载',
              v: <><b>平台管理员</b> 或 <b>工作空间管理员</b></>,
            },
            {
              k: '维护资源模版 (新建 / 编辑 / 删除)',
              v: (
                <>
                  <b>平台管理员</b> 或 <b>工作空间管理员</b>。
                  普通成员只能看, 不能改
                </>
              ),
            },
            {
              k: '看本团队全部任务 / 调任务优先级',
              v: <><b>平台管理员</b> 或 <b>工作空间管理员</b></>,
            },
            {
              k: '建 / 启停 / 删自己的开发机 · 训练 · 推理',
              v: <><b>所有人</b> (任何工作空间成员)</>,
            },
            {
              k: '停 / 删别人的开发机 / 训练',
              v: <><b>平台管理员</b> 或 <b>工作空间管理员</b></>,
            },
            {
              k: '平台级开关 (优先级档位、抢占)',
              v: <>仅<b>平台管理员</b></>,
            },
            {
              k: '生成自己的 API Token (脚本 / CI 用)',
              v: <><b>所有登录用户</b> 都可以为自己签</>,
            },
          ]}
        />
      </DocSection>

      <DocSection title="找不到按钮 · 怎么办" subTitle="Where's the button">
        <Paragraph style={{ marginBottom: 12 }}>
          界面是按身份隐藏入口的 — 看不到通常意味着"你不是这件事的负责角色"。常见三种情况:
        </Paragraph>
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>"想新建工作空间, 但没有按钮"</b> —
            建工作空间是平台管理员的事, 找平台管理员或者你的项目负责人帮你建。
          </li>
          <li>
            <b>"想拉同事进来, 但成员 Tab 没有「添加」按钮"</b> —
            加成员同样要平台管理员, 把同事的 username 报给他即可。
          </li>
          <li>
            <b>"想看团队里所有训练任务, 但只看得到自己的"</b> —
            这是普通成员视图; 让工作空间管理员或平台管理员看就行,
            或者请他们把你提为工作空间管理员。
          </li>
          <li>
            <b>"创建任务时挂载列表里没有那块盘"</b> —
            挂载需要管理员给你单独授权; 找工作空间管理员在 FSx Tab 把那块盘对你授权 (只读 / 读写)。
          </li>
        </ul>
      </DocSection>

      <DocSection title="加入 · 退出 · 升降级" subTitle="Lifecycle">
        <Paragraph style={{ marginBottom: 12 }}>
          所有的"成员变化"都立即生效 — 不需要重新登录:
        </Paragraph>
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>加入工作空间</b> — 平台管理员在工作空间详情页"成员 Tab"添加你, 你下次刷新就能看到。
          </li>
          <li>
            <b>提升 / 降级</b> — 同一个 Tab 里改"角色"字段; 升为工作空间管理员或降回普通成员都立即生效。
          </li>
          <li>
            <b>移除</b> — 同样在成员 Tab 删除; 你<b>正在跑的</b>开发机和训练任务不会被自动停掉,
            但之后你不能在这个空间创建 / 修改任何东西了。
          </li>
        </ul>
        <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 13 }}>
          被加到平台管理员是高权限动作, 不在界面上做, 由平台运维线下走流程。
        </Paragraph>
      </DocSection>

      <DocSection title="登录与切换身份" subTitle="Login">
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>登录后看不到任何工作空间</b> — 你还没被加进任何空间, 找项目负责人或平台管理员把你加进去。
          </li>
          <li>
            <b>同时属于多个工作空间</b> — 顶部的工作空间下拉框可以切换;
            切到不同空间, 左侧菜单和你的身份 (管理员 / 普通成员) 会跟着变。
          </li>
          <li>
            <b>跑脚本 / CI 想登录</b> — 顶部"获取 API Token"生成一个 token 放进脚本即可,
            身份和你浏览器里完全一致 (所以你脚本能做的事和你界面上能做的事是一样的)。
          </li>
          <li>
            <b>换了员工 / 改了用户名</b> — 用新身份重新登录浏览器即可; 旧 API Token 不会自动失效,
            如果不再用了请到顶部菜单里把它删了。
          </li>
        </ul>
      </DocSection>

      <DocSection title="常见误解" subTitle="Pitfalls">
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>"我看不到别人的任务 — 是 bug 吗?"</b> 不是, 这是设计 — 普通成员只看自己的;
            想看团队全貌, 让管理员把你提一下, 或让管理员去看。
          </li>
          <li>
            <b>"我是平台管理员, 但某个按钮没出来?"</b> 检查页面顶部当前选中的工作空间;
            如果停留在工作空间列表页, 部分操作要求先选定一个工作空间才会出现。
          </li>
          <li>
            <b>"我已经登录, 为什么操作弹「权限不足」?"</b> 看一眼右上角头像
            是不是你以为的那个 username; 公司换 SSO 帐号后, 必须在浏览器重新登录一次, 旧会话不会自动切换。
          </li>
          <li>
            <b>"我设了任务优先级, 但好像没起作用?"</b> 调优先级是工作空间管理员的能力;
            普通成员看到的优先级控件其实是只读的, 让管理员帮你调一下。
          </li>
          <li>
            <b>"我把同事从空间里删了, 他还在跑任务?"</b> 删成员不会自动停掉他正在跑的容器;
            如果需要立即下线, 请同时把他的开发机 / 训练任务也停掉。
          </li>
        </ul>
      </DocSection>
    </DocPage>
  );
}
