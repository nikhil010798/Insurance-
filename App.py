# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:

    leads = pd.read_sql_query(
        "SELECT * FROM leads ORDER BY updated_at DESC",
        DB
    )

    if leads.empty:
        renewals_30 = 0
        hot = 0

    else:
        leads["renewal_dt"] = pd.to_datetime(
            leads["renewal_date"],
            errors="coerce"
        ).dt.date

        renewals_30 = (
            (leads["renewal_dt"] >= date.today())
            &
            (
                leads["renewal_dt"]
                <= date.today() + timedelta(days=30)
            )
        ).sum()

        hot = (
            pd.to_numeric(
                leads["score"],
                errors="coerce"
            )
            .fillna(0)
            >= 70
        ).sum()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total Leads",
        len(leads)
    )

    c2.metric(
        "Renewals ≤30 Days",
        int(renewals_30)
    )

    c3.metric(
        "🔥 Hot Leads",
        int(hot)
    )

    c4.metric(
        "Verified Rate Rows",
        len(rates)
    )

    st.subheader("🔥 Sales Opportunity Scanner")

    if leads.empty:
        st.info(
            "Add customers from the CRM tab."
        )

    else:
        display = leads[
            [
                "name",
                "mobile",
                "insurer",
                "plan",
                "sum_insured",
                "renewal_date",
                "score"
            ]
        ].copy()

        display["Priority"] = np.where(
            display["score"] >= 80,
            "🔥 HOT",
            np.where(
                display["score"] >= 60,
                "🟠 WARM",
                "🟢 NURTURE"
            )
        )

        st.dataframe(
            display.sort_values(
                "score",
                ascending=False
            ),
            use_container_width=True,
            hide_index=True
        )
