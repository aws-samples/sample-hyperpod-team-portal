import { useEffect, useState } from 'react';
import { Tag } from 'antd';
import { listPriorityClasses } from '@/api/priority';

/**
 * 优先级档位标签 · 与「任务总览」优先级列同款:橙色 Tag + 后缀档位数值,
 * 形如 `common-priority (80)`。
 *
 * 数值来源:训练等模块只持久化档位名 (priority_class), 不带数值; 这里按名字查
 * WorkloadPriorityClass 字典 (/priority-classes) 拿 value。结果用模块级缓存,
 * 全站只打一次接口 (档位字典很少变, 变更需刷新页面)。
 */

// name -> value 缓存 (一次性加载, 所有实例共享)
let _cache: Record<string, number> | null = null;
let _inflight: Promise<Record<string, number>> | null = null;

function loadPriorityMap(): Promise<Record<string, number>> {
  if (_cache) return Promise.resolve(_cache);
  if (!_inflight) {
    _inflight = listPriorityClasses()
      .then((list) => {
        _cache = Object.fromEntries(list.map((p) => [p.name, p.value]));
        return _cache;
      })
      .catch(() => ({}) as Record<string, number>)
      .finally(() => {
        _inflight = null;
      });
  }
  return _inflight;
}

interface PriorityTagProps {
  /** 档位名 (空则用 fallbackName) */
  priorityClass?: string | null;
  /** 已知数值时直接传 (省一次查字典); 不传则按名字查 WPC */
  priorityValue?: number | null;
  /** 缺省档位名, 默认 common-priority */
  fallbackName?: string;
}

export default function PriorityTag({
  priorityClass,
  priorityValue,
  fallbackName = 'common-priority',
}: PriorityTagProps) {
  const name = priorityClass || fallbackName;
  const [value, setValue] = useState<number | null>(priorityValue ?? null);

  useEffect(() => {
    if (priorityValue != null) {
      setValue(priorityValue);
      return;
    }
    let cancelled = false;
    loadPriorityMap().then((m) => {
      if (!cancelled) setValue(m[name] ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [name, priorityValue]);

  return (
    <Tag color="orange">
      {name}
      {value != null ? ` (${value})` : ''}
    </Tag>
  );
}
