import { useTranslation } from 'react-i18next';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { HourlyFootfall } from '../api/models';
import { useFormat } from '../lib/prefs';

// Categorical pair validated for colour-vision deficiency (dataviz validate_palette.js, light).
export const SERIES_IN = '#0f9488';
export const SERIES_OUT = '#eb6834';

export function FootfallChart({ data }: { data: HourlyFootfall[] }) {
  const { t, i18n } = useTranslation();
  const fmt = useFormat();
  const rtl = i18n.dir() === 'rtl';
  const hourLabel = (h: number) => fmt.clock(`${String(h).padStart(2, '0')}:00`);
  const rows = data.map((d) => ({ ...d, label: hourLabel(d.hour) }));

  return (
    <div>
      <div className="h-64 w-full" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
            barGap={2}
            barCategoryGap="18%"
          >
            <CartesianGrid vertical={false} stroke="#e3e8ee" />
            <XAxis
              dataKey="label"
              reversed={rtl}
              tickLine={false}
              axisLine={{ stroke: '#cfd6de' }}
              tick={{ fontSize: 11, fill: '#5d6b78' }}
              interval="preserveStartEnd"
              minTickGap={12}
            />
            <YAxis
              orientation={rtl ? 'right' : 'left'}
              width={36}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              tick={{ fontSize: 11, fill: '#5d6b78' }}
              tickFormatter={(v: number) => fmt.number(v)}
            />
            <Tooltip
              cursor={{ fill: 'rgba(15,27,36,0.05)' }}
              formatter={(value, name) => [fmt.number(Number(value)), name]}
              contentStyle={{
                borderRadius: 8,
                borderColor: '#e3e8ee',
                fontSize: 12,
                direction: rtl ? 'rtl' : 'ltr',
              }}
            />
            <Legend
              verticalAlign="top"
              align={rtl ? 'right' : 'left'}
              height={28}
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12, color: '#33414d' }}
            />
            <Bar
              dataKey="in"
              name={t('overview.footfallIn')}
              fill={SERIES_IN}
              radius={[4, 4, 0, 0]}
              maxBarSize={14}
            />
            <Bar
              dataKey="out"
              name={t('overview.footfallOut')}
              fill={SERIES_OUT}
              radius={[4, 4, 0, 0]}
              maxBarSize={14}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-xs text-ink-500">{t('overview.showTable')}</summary>
        <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-line">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-canvas text-ink-500">
              <tr>
                <th scope="col" className="px-3 py-1.5 text-start font-medium">
                  {t('overview.hour')}
                </th>
                <th scope="col" className="px-3 py-1.5 text-end font-medium">
                  {t('overview.footfallIn')}
                </th>
                <th scope="col" className="px-3 py-1.5 text-end font-medium">
                  {t('overview.footfallOut')}
                </th>
              </tr>
            </thead>
            <tbody className="num divide-y divide-line">
              {rows.map((r) => (
                <tr key={r.hour}>
                  <td className="px-3 py-1">{r.label}</td>
                  <td className="px-3 py-1 text-end">{fmt.number(r.in)}</td>
                  <td className="px-3 py-1 text-end">{fmt.number(r.out)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
