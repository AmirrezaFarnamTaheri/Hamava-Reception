import { useState, type FormEvent } from "react";
import { Calculator, Plus } from "lucide-react";
import { errorText, faNumber, localToday, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Clinic } from "../types";
interface Contract {
  id: string;
  building_id: string;
  tenant_ids: string[];
  tenants: { id: string; name: string }[];
  contract_reference: string;
  included_minutes: number;
  overage_toman_per_minute: number;
  effective_period: string;
  created_at: string;
  draft: true;
}
interface Allocation {
  period: string;
  total_minutes: number;
  included_minutes_used: number;
  overage_minutes: number;
  overage_toman: number;
  items: {
    tenant_id: string;
    minutes: number;
    included_minutes: number;
    overage_toman: number;
  }[];
  draft: true;
}
function CreateContract({
  clinics,
  onClose,
  onSaved,
}: {
  clinics: Clinic[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const owned = clinics.filter(
    (item) => item.role === "owner" && item.building_id,
  );
  const groups = [...new Set(owned.map((item) => item.building_id!))];
  const [building, setBuilding] = useState(groups[0] || "");
  const [tenants, setTenants] = useState<string[]>([]);
  const [reference, setReference] = useState("");
  const [minutes, setMinutes] = useState(0);
  const [rate, setRate] = useState(0);
  const [period, setPeriod] = useState(localToday().slice(0, 7));
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/building-contracts", {
        building_id: building,
        tenant_ids: tenants,
        contract_reference: reference,
        included_minutes: minutes,
        overage_toman_per_minute: rate,
        effective_period: period,
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ثبت قرارداد مصرف مشترک"
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Field label="مجموعهٔ مراکز هم‌ساختمان">
          <select
            required
            value={building}
            onChange={(e) => {
              setBuilding(e.target.value);
              setTenants([]);
            }}
          >
            <option value="">انتخاب کنید</option>
            {groups.map((id) => (
              <option key={id} value={id}>
                {owned
                  .filter((clinic) => clinic.building_id === id)
                  .map((clinic) => clinic.name)
                  .join("، ")}
              </option>
            ))}
          </select>
        </Field>
        <fieldset className="scope-options">
          <legend>مراکز عضو قرارداد</legend>
          {owned
            .filter((clinic) => clinic.building_id === building)
            .map((clinic) => (
              <label className="check-field" key={clinic.id}>
                <input
                  type="checkbox"
                  checked={tenants.includes(clinic.id)}
                  onChange={(e) =>
                    setTenants(
                      e.target.checked
                        ? [...tenants, clinic.id]
                        : tenants.filter((id) => id !== clinic.id),
                    )
                  }
                />
                <span>{clinic.name}</span>
              </label>
            ))}
        </fieldset>
        <Field label="مرجع قرارداد مصوب">
          <input
            required
            minLength={5}
            maxLength={200}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label="دقایق مشترکِ شامل قرارداد">
            <input
              required
              type="number"
              min={0}
              max={10000000}
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
            />
          </Field>
          <Field label="هر دقیقهٔ مازاد (تومان)">
            <input
              required
              type="number"
              min={0}
              max={100000000}
              value={rate}
              onChange={(e) => setRate(Number(e.target.value))}
            />
          </Field>
          <Field label="ماه شروع قرارداد (میلادی)">
            <input
              required
              type="month"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            />
          </Field>
        </div>
        <Alert kind="info">
          محاسبهٔ سهم بر پایهٔ مصرف ثبت‌شده است. حق اشتراک پایه و مالیات جدا
          هستند. این ثبت و محاسبه، هیچ مبلغی برداشت نمی‌کند.
        </Alert>
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            اختیار مراکز عضو، مفاد و ارقام قرارداد را بررسی و تأیید کرده‌ام.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !confirmed || !tenants.length}
          >
            <Busy busy={busy}>ثبت قرارداد مشترک</Busy>
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            بازگشت
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function AllocationView({
  contract,
  onClose,
}: {
  contract: Contract;
  onClose: () => void;
}) {
  const [period, setPeriod] = useState(
    localToday().slice(0, 7) < contract.effective_period
      ? contract.effective_period
      : localToday().slice(0, 7),
  );
  const result = useRemote<Allocation>(
    `/operations/building-contracts/${contract.id}/allocation?period=${period}`,
  );
  return (
    <Dialog title="پیش‌نویس سهم مصرف مشترک" wide onClose={onClose}>
      <div className="modal-body">
        <div className="selected-appointment">
          <strong>{contract.contract_reference}</strong>
          <span>{contract.tenants.map((item) => item.name).join("، ")}</span>
          <Status value="DRAFT" />
        </div>
        <Field label="ماه محاسبه (میلادی)">
          <input
            type="month"
            required
            min={contract.effective_period}
            value={period}
            onChange={(e) => {
              if (e.target.value) setPeriod(e.target.value);
            }}
          />
        </Field>
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : (
          result.data && (
            <>
              <dl className="digest-facts">
                <div>
                  <dt>مصرف کل</dt>
                  <dd>{faNumber(result.data.total_minutes)} دقیقه</dd>
                </div>
                <div>
                  <dt>مصرف مشمول قرارداد</dt>
                  <dd>{faNumber(result.data.included_minutes_used)} دقیقه</dd>
                </div>
                <div>
                  <dt>مازاد</dt>
                  <dd>{faNumber(result.data.overage_minutes)} دقیقه</dd>
                </div>
                <div>
                  <dt>مبلغ مازاد کل</dt>
                  <dd>{faNumber(result.data.overage_toman)} تومان</dd>
                </div>
              </dl>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="تقسیم مصرف مشترک"
              >
                <table>
                  <thead>
                    <tr>
                      <th>مرکز</th>
                      <th>دقیقهٔ مصرف</th>
                      <th>دقیقهٔ مشمول قرارداد</th>
                      <th>سهم مازاد</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.data.items.map((item) => (
                      <tr key={item.tenant_id}>
                        <td>
                          {contract.tenants.find(
                            (tenant) => tenant.id === item.tenant_id,
                          )?.name || "مرکز مجاز"}
                        </td>
                        <td>{faNumber(item.minutes)}</td>
                        <td>{faNumber(item.included_minutes)}</td>
                        <td>{faNumber(item.overage_toman)} تومان</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="field-hint">
                سهم‌ها به نسبت مصرف تقسیم می‌شوند و گرد کردن تومان طوری انجام
                می‌شود که جمع سهم‌ها با مبلغ کل برابر بماند. این پیش‌نویس،
                صورتحساب قطعی یا دریافت وجه نیست.
              </p>
            </>
          )
        )}
        <div className="modal-actions">
          <button className="button secondary" onClick={onClose}>
            بستن
          </button>
        </div>
      </div>
    </Dialog>
  );
}
export function BuildingContracts() {
  const result = useRemote<Contract[]>("/operations/building-contracts");
  const clinics = useRemote<Clinic[]>("/clinics");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Contract | null>(null);
  const [message, setMessage] = useState("");
  const eligible = clinics.data?.some(
    (item) => item.role === "owner" && item.building_id,
  );
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel catalog-panel">
        <SectionTitle
          title="قرارداد و سهم مصرف مشترک"
          description="قراردادهای مجازِ ساختمان و پیش‌نویس تقسیم هزینه بر اساس مصرف واقعی."
          action={
            <button
              className="button primary small"
              disabled={!eligible}
              onClick={() => setAdding(true)}
            >
              <Plus size={16} />
              قرارداد مشترک
            </button>
          }
        />
        {clinics.error && (
          <Retry error={clinics.error} onRetry={clinics.refresh} />
        )}{" "}
        {!clinics.loading && !eligible && (
          <div className="panel-notice">
            <Alert kind="info">
              برای این حساب، مرکزِ دارای اختیار مالک و عضویت ساختمان ثبت نشده
              است. عضویت ساختمان باید پیش از قرارداد تعیین شود.
            </Alert>
          </div>
        )}
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={2} />
        ) : result.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="قراردادهای مصرف مشترک"
          >
            <table>
              <thead>
                <tr>
                  <th>مرجع قرارداد</th>
                  <th>مراکز</th>
                  <th>دقیقهٔ مشمول</th>
                  <th>تعرفهٔ مازاد</th>
                  <th>محاسبه</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.contract_reference}</strong>
                      <small className="table-subline">
                        از ماه {faNumber(item.effective_period)} میلادی
                      </small>
                    </td>
                    <td>
                      {item.tenants.map((tenant) => tenant.name).join("، ")}
                    </td>
                    <td>{faNumber(item.included_minutes)}</td>
                    <td>{faNumber(item.overage_toman_per_minute)} تومان</td>
                    <td>
                      <button
                        className="button secondary small"
                        onClick={() => setSelected(item)}
                      >
                        <Calculator size={16} />
                        پیش‌نویس سهم
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="قرارداد مشترکی ثبت نشده"
            description="ثبت قرارداد به اختیار مالک برای تمام مراکز عضو همان ساختمان نیاز دارد."
          />
        )}
      </section>
      {adding && (
        <CreateContract
          clinics={clinics.data || []}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            result.refresh();
            setMessage(
              "قرارداد مصرف مشترک ثبت شد؛ محاسبهٔ سهم همچنان پیش‌نویس است.",
            );
          }}
        />
      )}
      {selected && (
        <AllocationView contract={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}
