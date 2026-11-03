import type { Dayjs } from 'dayjs';

/**
 * 日志时间选择器联动禁用: 开始不得晚于结束, 结束不得早于开始。
 * disabledDate 只能按天禁用; showTime 下同一天内还需 disabledTime 卡时分秒。
 * Pod 日志 / 任务日志两个组件共用。
 */

const hms = (d: Dayjs) => ({ h: d.hour(), m: d.minute(), s: d.second() });

const range = (from: number, to: number): number[] => {
  const r: number[] = [];
  for (let i = from; i <= to; i++) r.push(i);
  return r;
};

/** 传入当前 start/end, 返回两个选择器的 disabledDate/disabledTime。 */
export function buildTimeConstraints(startAt: Dayjs | null, endAt: Dayjs | null) {
  return {
    // 开始选择器: 禁用晚于 endAt 的日期/时刻
    disabledStartDate: (d: Dayjs) => !!endAt && d.isAfter(endAt, 'day'),
    disabledStartTime: (d: Dayjs | null) => {
      if (!endAt || !d || !d.isSame(endAt, 'day')) return {};
      const e = hms(endAt);
      return {
        disabledHours: () => range(e.h + 1, 23),
        disabledMinutes: (h: number) => (h === e.h ? range(e.m + 1, 59) : []),
        disabledSeconds: (h: number, m: number) =>
          h === e.h && m === e.m ? range(e.s + 1, 59) : [],
      };
    },
    // 结束选择器: 禁用早于 startAt 的日期/时刻
    disabledEndDate: (d: Dayjs) => !!startAt && d.isBefore(startAt, 'day'),
    disabledEndTime: (d: Dayjs | null) => {
      if (!startAt || !d || !d.isSame(startAt, 'day')) return {};
      const s = hms(startAt);
      return {
        disabledHours: () => range(0, s.h - 1),
        disabledMinutes: (h: number) => (h === s.h ? range(0, s.m - 1) : []),
        disabledSeconds: (h: number, m: number) =>
          h === s.h && m === s.m ? range(0, s.s - 1) : [],
      };
    },
  };
}
