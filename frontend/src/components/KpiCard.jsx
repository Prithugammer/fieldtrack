/** A dashboard metric tile. tone: navy | orange | green | amber (colour of the left accent bar). */
export default function KpiCard({ label, value, hint, tone = 'navy' }) {
  return (
    <div className={`card kpi kpi--${tone}`}>
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">{value}</div>
      {hint && <div className="kpi__hint">{hint}</div>}
    </div>
  )
}
