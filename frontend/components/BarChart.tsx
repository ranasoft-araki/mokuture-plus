interface Props {
  data: { date: string; count: number }[]
  barColor?: string
  height?: number
}

export default function BarChart({ data, barColor = '#2d6a4f', height = 80 }: Props) {
  const max = Math.max(...data.map(d => d.count), 1)

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: height, marginTop: 8 }}>
      {data.map((item, i) => {
        const barH = Math.max((item.count / max) * height, item.count > 0 ? 2 : 1)
        const isToday = item.date === new Date().toISOString().slice(0, 10)
        const label = new Date(item.date).toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' })

        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }} title={`${label}: ${item.count}件`}>
            <div style={{ fontSize: 9, color: '#a8a198', lineHeight: 1 }}>
              {item.count > 0 ? item.count : ''}
            </div>
            <div style={{
              width: '100%', height: barH,
              background: isToday ? barColor : barColor + '80',
              borderRadius: '2px 2px 0 0',
              transition: 'height 0.3s ease'
            }} />
            <div style={{ fontSize: 8, color: '#a8a198', lineHeight: 1, whiteSpace: 'nowrap' }}>
              {i % 2 === 0 ? label : ''}
            </div>
          </div>
        )
      })}
    </div>
  )
}
