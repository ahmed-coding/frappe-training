# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	cint,
	date_diff,
	flt,
	get_first_day,
	get_last_day,
	getdate,
	is_last_day_of_the_month,
	month_diff,
)

import erpnext


class AssetDepreciationSchedule(Document):
	def before_save(self):
		if not self.finance_book_id:
			self.prepare_draft_asset_depr_schedule_data_from_asset_name_and_fb_name(
				self.asset, self.finance_book
			)

	def validate(self):
		self.validate_another_asset_depr_schedule_does_not_exist()

	def validate_another_asset_depr_schedule_does_not_exist(self):
		finance_book_filter = ["finance_book", "is", "not set"]
		if self.finance_book:
			finance_book_filter = ["finance_book", "=", self.finance_book]

		asset_depr_schedule = frappe.db.exists(
			"Asset Depreciation Schedule",
			[
				["asset", "=", self.asset],
				finance_book_filter,
				["docstatus", "<", 2],
			],
		)

		if asset_depr_schedule and asset_depr_schedule != self.name:
			if self.finance_book:
				frappe.throw(
					_(
						"Asset Depreciation Schedule {0} for Asset {1} and Finance Book {2} already exists."
					).format(asset_depr_schedule, self.asset, self.finance_book)
				)
			else:
				frappe.throw(
					_("Asset Depreciation Schedule {0} for Asset {1} already exists.").format(
						asset_depr_schedule, self.asset
					)
				)

	def on_submit(self):
		self.db_set("status", "Active")

	def before_cancel(self):
		if not self.flags.should_not_cancel_depreciation_entries:
			self.cancel_depreciation_entries()

	def cancel_depreciation_entries(self):
		for d in self.get("depreciation_schedule"):
			if d.journal_entry:
				frappe.get_doc("Journal Entry", d.journal_entry).cancel()

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def prepare_draft_asset_depr_schedule_data_from_asset_name_and_fb_name(self, asset_name, fb_name):
		asset_doc = frappe.get_doc("Asset", asset_name)

		finance_book_filter = ["finance_book", "is", "not set"]
		if fb_name:
			finance_book_filter = ["finance_book", "=", fb_name]

		asset_finance_book_name = frappe.db.get_value(
			doctype="Asset Finance Book",
			filters=[["parent", "=", asset_name], finance_book_filter],
		)
		asset_finance_book_doc = frappe.get_doc("Asset Finance Book", asset_finance_book_name)

		self.prepare_draft_asset_depr_schedule_data(asset_doc, asset_finance_book_doc)

	def prepare_draft_asset_depr_schedule_data(
		self,
		asset_doc,
		row,
		date_of_disposal=None,
		date_of_return=None,
		update_asset_finance_book_row=True,
	):
		have_asset_details_been_modified = self.have_asset_details_been_modified(asset_doc)
		not_manual_depr_or_have_manual_depr_details_been_modified = (
			self.not_manual_depr_or_have_manual_depr_details_been_modified(row)
		)

		self.set_draft_asset_depr_schedule_details(asset_doc, row)

		if self.should_prepare_depreciation_schedule(
			have_asset_details_been_modified, not_manual_depr_or_have_manual_depr_details_been_modified
		):
			self.make_depr_schedule(asset_doc, row, date_of_disposal, update_asset_finance_book_row)
			self.set_accumulated_depreciation(asset_doc, row, date_of_disposal, date_of_return)

	def have_asset_details_been_modified(self, asset_doc):
		return (
			asset_doc.gross_purchase_amount != self.gross_purchase_amount
			or asset_doc.opening_accumulated_depreciation != self.opening_accumulated_depreciation
			or asset_doc.number_of_depreciations_booked != self.number_of_depreciations_booked
		)

	def not_manual_depr_or_have_manual_depr_details_been_modified(self, row):
		return (
			self.depreciation_method != "Manual"
			or row.total_number_of_depreciations != self.total_number_of_depreciations
			or row.frequency_of_depreciation != self.frequency_of_depreciation
			or getdate(row.depreciation_start_date) != self.get("depreciation_schedule")[0].schedule_date
			or row.expected_value_after_useful_life != self.expected_value_after_useful_life
		)

	def should_prepare_depreciation_schedule(
		self, have_asset_details_been_modified, not_manual_depr_or_have_manual_depr_details_been_modified
	):
		if not self.get("depreciation_schedule"):
			return True

		old_asset_depr_schedule_doc = self.get_doc_before_save()

		if self.docstatus != 0 and not old_asset_depr_schedule_doc:
			return True

		if have_asset_details_been_modified or not_manual_depr_or_have_manual_depr_details_been_modified:
			return True

		return False

	def set_draft_asset_depr_schedule_details(self, asset_doc, row):
		self.asset = asset_doc.name
		self.finance_book = row.finance_book
		self.finance_book_id = row.idx
		self.opening_accumulated_depreciation = asset_doc.opening_accumulated_depreciation or 0
		self.number_of_depreciations_booked = asset_doc.number_of_depreciations_booked or 0
		self.gross_purchase_amount = asset_doc.gross_purchase_amount
		self.depreciation_method = row.depreciation_method
		self.total_number_of_depreciations = row.total_number_of_depreciations
		self.frequency_of_depreciation = row.frequency_of_depreciation
		self.rate_of_depreciation = row.rate_of_depreciation
		self.expected_value_after_useful_life = row.expected_value_after_useful_life
		self.daily_prorata_based = row.daily_prorata_based
		self.status = "Draft"

	def make_depr_schedule(
		self,
		asset_doc,
		row,
		date_of_disposal,
		update_asset_finance_book_row=True,
		value_after_depreciation=None,
	):
		if not self.get("depreciation_schedule"):
			self.depreciation_schedule = []

		if not asset_doc.available_for_use_date:
			return

		start = self.clear_depr_schedule()

		self._make_depr_schedule(
			asset_doc, row, start, date_of_disposal, update_asset_finance_book_row, value_after_depreciation
		)

	def clear_depr_schedule(self):
		start = 0
		num_of_depreciations_completed = 0
		depr_schedule = []

		for schedule in self.get("depreciation_schedule"):
			if schedule.journal_entry:
				num_of_depreciations_completed += 1
				depr_schedule.append(schedule)
			else:
				start = num_of_depreciations_completed
				break

		self.depreciation_schedule = depr_schedule

		return start

	def _make_depr_schedule(
		self,
		asset_doc,
		row,
		start,
		date_of_disposal,
		update_asset_finance_book_row,
		value_after_depreciation,
	):
		asset_doc.validate_asset_finance_books(row)

		if not value_after_depreciation:
			value_after_depreciation = _get_value_after_depreciation_for_making_schedule(asset_doc, row)
		row.value_after_depreciation = value_after_depreciation

		if update_asset_finance_book_row:
			row.db_update()

		final_number_of_depreciations = cint(row.total_number_of_depreciations) - cint(
			self.number_of_depreciations_booked
		)

		has_pro_rata = _check_is_pro_rata(asset_doc, row)
		if has_pro_rata:
			final_number_of_depreciations += 1

		has_wdv_or_dd_non_yearly_pro_rata = False
		if (
			row.depreciation_method in ("Written Down Value", "Double Declining Balance")
			and cint(row.frequency_of_depreciation) != 12
		):
			has_wdv_or_dd_non_yearly_pro_rata = _check_is_pro_rata(
				asset_doc, row, wdv_or_dd_non_yearly=True
			)

		skip_row = False
		should_get_last_day = is_last_day_of_the_month(row.depreciation_start_date)

		depreciation_amount = 0

		number_of_pending_depreciations = final_number_of_depreciations - start

		for n in range(start, final_number_of_depreciations):
			# If depreciation is already completed (for double declining balance)
			if skip_row:
				continue

			if n > 0 and len(self.get("depreciation_schedule")) > n - 1:
				prev_depreciation_amount = self.get("depreciation_schedule")[n - 1].depreciation_amount
			else:
				prev_depreciation_amount = 0

			depreciation_amount = get_depreciation_amount(
				asset_doc,
				value_after_depreciation,
				row,
				n,
				prev_depreciation_amount,
				has_wdv_or_dd_non_yearly_pro_rata,
				number_of_pending_depreciations,
			)

			if not has_pro_rata or (
				n < (cint(final_number_of_depreciations) - 1) or final_number_of_depreciations == 2
			):
				schedule_date = add_months(
					row.depreciation_start_date, n * cint(row.frequency_of_depreciation)
				)

				if should_get_last_day:
					schedule_date = get_last_day(schedule_date)

			# if asset is being sold or scrapped
			if date_of_disposal:
				from_date = add_months(
					getdate(asset_doc.available_for_use_date),
					(asset_doc.number_of_depreciations_booked * row.frequency_of_depreciation),
				)
				if self.depreciation_schedule:
					from_date = self.depreciation_schedule[-1].schedule_date

				depreciation_amount, days, months = _get_pro_rata_amt(
					row,
					depreciation_amount,
					from_date,
					date_of_disposal,
				)

				if depreciation_amount > 0:
					self.add_depr_schedule_row(
						date_of_disposal,
						depreciation_amount,
					)

				break

			# For first row
			if (
				n == 0
				and (has_pro_rata or has_wdv_or_dd_non_yearly_pro_rata)
				and not self.opening_accumulated_depreciation
			):
				from_date = add_days(
					asset_doc.available_for_use_date, -1
				)  # needed to calc depr amount for available_for_use_date too
				depreciation_amount, days, months = _get_pro_rata_amt(
					row,
					depreciation_amount,
					from_date,
					row.depreciation_start_date,
					has_wdv_or_dd_non_yearly_pro_rata,
				)
			elif n == 0 and has_wdv_or_dd_non_yearly_pro_rata and self.opening_accumulated_depreciation:
				if not is_first_day_of_the_month(getdate(asset_doc.available_for_use_date)):
					from_date = get_last_day(
						add_months(
							getdate(asset_doc.available_for_use_date),
							((self.number_of_depreciations_booked - 1) * row.frequency_of_depreciation),
						)
					)
				else:
					from_date = add_months(
						getdate(add_days(asset_doc.available_for_use_date, -1)),
						(self.number_of_depreciations_booked * row.frequency_of_depreciation),
					)
				depreciation_amount, days, months = _get_pro_rata_amt(
					row,
					depreciation_amount,
					from_date,
					row.depreciation_start_date,
					has_wdv_or_dd_non_yearly_pro_rata,
				)

			# For last row
			elif has_pro_rata and n == cint(final_number_of_depreciations) - 1:
				if not asset_doc.flags.increase_in_asset_life:
					# In case of increase_in_asset_life, the asset.to_date is already set on asset_repair submission
					asset_doc.to_date = add_months(
						asset_doc.available_for_use_date,
						(n + self.number_of_depreciations_booked) * cint(row.frequency_of_depreciation),
					)

				depreciation_amount_without_pro_rata = depreciation_amount

				depreciation_amount, days, months = _get_pro_rata_amt(
					row,
					depreciation_amount,
					schedule_date,
					asset_doc.to_date,
					has_wdv_or_dd_non_yearly_pro_rata,
				)

				depreciation_amount = self.get_adjusted_depreciation_amount(
					depreciation_amount_without_pro_rata, depreciation_amount
				)

				schedule_date = add_days(schedule_date, days)

			if not depreciation_amount:
				continue
			value_after_depreciation -= flt(
				depreciation_amount, asset_doc.precision("gross_purchase_amount")
			)

			# Adjust depreciation amount in the last period based on the expected value after useful life
			if row.expected_value_after_useful_life and (
				(
					n == cint(final_number_of_depreciations) - 1
					and value_after_depreciation != row.expected_value_after_useful_life
				)
				or value_after_depreciation < row.expected_value_after_useful_life
			):
				depreciation_amount += value_after_depreciation - row.expected_value_after_useful_life
				skip_row = True

			if flt(depreciation_amount, asset_doc.precision("gross_purchase_amount")) > 0:
				self.add_depr_schedule_row(
					schedule_date,
					depreciation_amount,
				)

	# to ensure that final accumulated depreciation amount is accurate
	def get_adjusted_depreciation_amount(
		self, depreciation_amount_without_pro_rata, depreciation_amount_for_last_row
	):
		if not self.opening_accumulated_depreciation:
			depreciation_amount_for_first_row = self.get_depreciation_amount_for_first_row()

			if (
				depreciation_amount_for_first_row + depreciation_amount_for_last_row
				!= depreciation_amount_without_pro_rata
			):
				depreciation_amount_for_last_row = (
					depreciation_amount_without_pro_rata - depreciation_amount_for_first_row
				)

		return depreciation_amount_for_last_row

	def get_depreciation_amount_for_first_row(self):
		return self.get("depreciation_schedule")[0].depreciation_amount

	def add_depr_schedule_row(
		self,
		schedule_date,
		depreciation_amount,
	):
		self.append(
			"depreciation_schedule",
			{
				"schedule_date": schedule_date,
				"depreciation_amount": depreciation_amount,
			},
		)

	def set_accumulated_depreciation(
		self,
		asset_doc,
		row,
		date_of_disposal=None,
		date_of_return=None,
		ignore_booked_entry=False,
	):
		straight_line_idx = [
			d.idx
			for d in self.get("depreciation_schedule")
			if self.depreciation_method == "Straight Line" or self.depreciation_method == "Manual"
		]

		accumulated_depreciation = None
		value_after_depreciation = flt(row.value_after_depreciation)

		for i, d in enumerate(self.get("depreciation_schedule")):
			if ignore_booked_entry and d.journal_entry:
				continue

			if not accumulated_depreciation:
				if i > 0 and asset_doc.flags.decrease_in_asset_value_due_to_value_adjustment:
					accumulated_depreciation = self.get("depreciation_schedule")[
						i - 1
					].accumulated_depreciation_amount
				else:
					accumulated_depreciation = flt(self.opening_accumulated_depreciation)

			depreciation_amount = flt(d.depreciation_amount, d.precision("depreciation_amount"))
			value_after_depreciation -= flt(depreciation_amount)

			# for the last row, if depreciation method = Straight Line
			if (
				straight_line_idx
				and i == max(straight_line_idx) - 1
				and not date_of_disposal
				and not date_of_return
			):
				depreciation_amount += flt(
					value_after_depreciation - flt(row.expected_value_after_useful_life),
					d.precision("depreciation_amount"),
				)

			d.depreciation_amount = depreciation_amount
			accumulated_depreciation += d.depreciation_amount
			d.accumulated_depreciation_amount = flt(
				accumulated_depreciation, d.precision("accumulated_depreciation_amount")
			)


def _get_value_after_depreciation_for_making_schedule(asset_doc, fb_row):
	if asset_doc.docstatus == 1 and fb_row.value_after_depreciation:
		value_after_depreciation = flt(fb_row.value_after_depreciation)
	else:
		value_after_depreciation = flt(asset_doc.gross_purchase_amount) - flt(
			asset_doc.opening_accumulated_depreciation
		)

	return value_after_depreciation


# if it returns True, depreciation_amount will not be equal for the first and last rows
def _check_is_pro_rata(asset_doc, row, wdv_or_dd_non_yearly=False):
	has_pro_rata = False

	# if not existing asset, from_date = available_for_use_date
	# otherwise, if number_of_depreciations_booked = 2, available_for_use_date = 01/01/2020 and frequency_of_depreciation = 12
	# from_date = 01/01/2022
	from_date = _get_modified_available_for_use_date(asset_doc, row, wdv_or_dd_non_yearly)
	days = date_diff(row.depreciation_start_date, from_date) + 1

	if wdv_or_dd_non_yearly:
		total_days = get_total_days(row.depreciation_start_date, 12)
	else:
		# if frequency_of_depreciation is 12 months, total_days = 365
		total_days = get_total_days(row.depreciation_start_date, row.frequency_of_depreciation)

	if days < total_days:
		has_pro_rata = True

	return has_pro_rata


def _get_modified_available_for_use_date(asset_doc, row, wdv_or_dd_non_yearly=False):
	if wdv_or_dd_non_yearly:
		return add_months(
			asset_doc.available_for_use_date,
			(asset_doc.number_of_depreciations_booked * 12),
		)
	else:
		return add_months(
			asset_doc.available_for_use_date,
			(asset_doc.number_of_depreciations_booked * row.frequency_of_depreciation),
		)


def _get_pro_rata_amt(
	row, depreciation_amount, from_date, to_date, has_wdv_or_dd_non_yearly_pro_rata=False
):
	days = date_diff(to_date, from_date)
	months = month_diff(to_date, from_date)
	if has_wdv_or_dd_non_yearly_pro_rata:
		total_days = get_total_days(to_date, 12)
	else:
		total_days = get_total_days(to_date, row.frequency_of_depreciation)

	return (depreciation_amount * flt(days)) / flt(total_days), days, months


def get_total_days(date, frequency):
	period_start_date = add_months(date, cint(frequency) * -1)

	if is_last_day_of_the_month(date):
		period_start_date = get_last_day(period_start_date)

	return date_diff(date, period_start_date)


def get_depreciation_amount(
	asset,
	depreciable_value,
	fb_row,
	schedule_idx=0,
	prev_depreciation_amount=0,
	has_wdv_or_dd_non_yearly_pro_rata=False,
	number_of_pending_depreciations=0,
):
	if fb_row.depreciation_method in ("Straight Line", "Manual"):
		return get_straight_line_or_manual_depr_amount(
			asset, fb_row, schedule_idx, number_of_pending_depreciations
		)
	else:
		rate_of_depreciation = get_updated_rate_of_depreciation_for_wdv_and_dd(
			asset, depreciable_value, fb_row
		)
		return get_wdv_or_dd_depr_amount(
			depreciable_value,
			rate_of_depreciation,
			fb_row.frequency_of_depreciation,
			schedule_idx,
			prev_depreciation_amount,
			has_wdv_or_dd_non_yearly_pro_rata,
		)


@erpnext.allow_regional
def get_updated_rate_of_depreciation_for_wdv_and_dd(asset, depreciable_value, fb_row):
	return fb_row.rate_of_depreciation


def get_straight_line_or_manual_depr_amount(
	asset, row, schedule_idx, number_of_pending_depreciations
):
	# if the Depreciation Schedule is being modified after Asset Repair due to increase in asset life and value
	if asset.flags.increase_in_asset_life:
		return (flt(row.value_after_depreciation) - flt(row.expected_value_after_useful_life)) / (
			date_diff(asset.to_date, asset.available_for_use_date) / 365
		)
	# if the Depreciation Schedule is being modified after Asset Repair due to increase in asset value
	elif asset.flags.increase_in_asset_value_due_to_repair:
		return (flt(row.value_after_depreciation) - flt(row.expected_value_after_useful_life)) / flt(
			row.total_number_of_depreciations
		)
	# if the Depreciation Schedule is being modified after Asset Value Adjustment due to decrease in asset value
	elif asset.flags.decrease_in_asset_value_due_to_value_adjustment:
		if row.daily_prorata_based:
			daily_depr_amount = (
				flt(row.value_after_depreciation) - flt(row.expected_value_after_useful_life)
			) / date_diff(
				get_last_day(
					add_months(
						row.depreciation_start_date,
						flt(row.total_number_of_depreciations - asset.number_of_depreciations_booked - 1)
						* row.frequency_of_depreciation,
					)
				),
				add_days(
					get_last_day(
						add_months(
							row.depreciation_start_date,
							flt(
								row.total_number_of_depreciations
								- asset.number_of_depreciations_booked
								- number_of_pending_depreciations
								- 1
							)
							* row.frequency_of_depreciation,
						)
					),
					1,
				),
			)

			to_date = get_last_day(
				add_months(row.depreciation_start_date, schedule_idx * row.frequency_of_depreciation)
			)
			from_date = add_days(
				get_last_day(
					add_months(row.depreciation_start_date, (schedule_idx - 1) * row.frequency_of_depreciation)
				),
				1,
			)

			return daily_depr_amount * (date_diff(to_date, from_date) + 1)
		else:
			return (
				flt(row.value_after_depreciation) - flt(row.expected_value_after_useful_life)
			) / number_of_pending_depreciations
	# if the Depreciation Schedule is being prepared for the first time
	else:
		if row.daily_prorata_based:
			daily_depr_amount = (
				flt(asset.gross_purchase_amount)
				- flt(asset.opening_accumulated_depreciation)
				- flt(row.expected_value_after_useful_life)
			) / date_diff(
				get_last_day(
					add_months(
						row.depreciation_start_date,
						flt(row.total_number_of_depreciations - asset.number_of_depreciations_booked - 1)
						* row.frequency_of_depreciation,
					)
				),
				add_days(
					get_last_day(add_months(row.depreciation_start_date, -1 * row.frequency_of_depreciation)), 1
				),
			)

			to_date = get_last_day(
				add_months(row.depreciation_start_date, schedule_idx * row.frequency_of_depreciation)
			)
			from_date = add_days(
				get_last_day(
					add_months(row.depreciation_start_date, (schedule_idx - 1) * row.frequency_of_depreciation)
				),
				1,
			)

			return daily_depr_amount * (date_diff(to_date, from_date) + 1)
		else:
			return (
				flt(asset.gross_purchase_amount)
				- flt(asset.opening_accumulated_depreciation)
				- flt(row.expected_value_after_useful_life)
			) / flt(row.total_number_of_depreciations - asset.number_of_depreciations_booked)


def get_wdv_or_dd_depr_amount(
	depreciable_value,
	rate_of_depreciation,
	frequency_of_depreciation,
	schedule_idx,
	prev_depreciation_amount,
	has_wdv_or_dd_non_yearly_pro_rata,
):
	if cint(frequency_of_depreciation) == 12:
		return flt(depreciable_value) * (flt(rate_of_depreciation) / 100)
	else:
		if has_wdv_or_dd_non_yearly_pro_rata:
			if schedule_idx == 0:
				return flt(depreciable_value) * (flt(rate_of_depreciation) / 100)
			elif schedule_idx % (12 / cint(frequency_of_depreciation)) == 1:
				return (
					flt(depreciable_value) * flt(frequency_of_depreciation) * (flt(rate_of_depreciation) / 1200)
				)
			else:
				return prev_depreciation_amount
		else:
			if schedule_idx % (12 / cint(frequency_of_depreciation)) == 0:
				return (
					flt(depreciable_value) * flt(frequency_of_depreciation) * (flt(rate_of_depreciation) / 1200)
				)
			else:
				return prev_depreciation_amount


def make_draft_asset_depr_schedules_if_not_present(asset_doc):
	asset_depr_schedules_names = []

	for row in asset_doc.get("finance_books"):
		draft_asset_depr_schedule_name = get_asset_depr_schedule_name(
			asset_doc.name, "Draft", row.finance_book
		)

		active_asset_depr_schedule_name = get_asset_depr_schedule_name(
			asset_doc.name, "Active", row.finance_book
		)

		if not draft_asset_depr_schedule_name and not active_asset_depr_schedule_name:
			name = make_draft_asset_depr_schedule(asset_doc, row)
			asset_depr_schedules_names.append(name)

	return asset_depr_schedules_names


def make_draft_asset_depr_schedules(asset_doc):
	asset_depr_schedules_names = []

	for row in asset_doc.get("finance_books"):
		name = make_draft_asset_depr_schedule(asset_doc, row)
		asset_depr_schedules_names.append(name)

	return asset_depr_schedules_names


def make_draft_asset_depr_schedule(asset_doc, row):
	asset_depr_schedule_doc = frappe.new_doc("Asset Depreciation Schedule")

	asset_depr_schedule_doc.prepare_draft_asset_depr_schedule_data(asset_doc, row)

	asset_depr_schedule_doc.insert()

	return asset_depr_schedule_doc.name


def update_draft_asset_depr_schedules(asset_doc):
	for row in asset_doc.get("finance_books"):
		asset_depr_schedule_doc = get_asset_depr_schedule_doc(asset_doc.name, "Draft", row.finance_book)

		if not asset_depr_schedule_doc:
			continue

		asset_depr_schedule_doc.prepare_draft_asset_depr_schedule_data(asset_doc, row)

		asset_depr_schedule_doc.save()


def convert_draft_asset_depr_schedules_into_active(asset_doc):
	for row in asset_doc.get("finance_books"):
		asset_depr_schedule_doc = get_asset_depr_schedule_doc(asset_doc.name, "Draft", row.finance_book)

		if not asset_depr_schedule_doc:
			continue

		asset_depr_schedule_doc.submit()


def cancel_asset_depr_schedules(asset_doc):
	for row in asset_doc.get("finance_books"):
		asset_depr_schedule_doc = get_asset_depr_schedule_doc(asset_doc.name, "Active", row.finance_book)

		if not asset_depr_schedule_doc:
			continue

		asset_depr_schedule_doc.cancel()


def make_new_active_asset_depr_schedules_and_cancel_current_ones(
	asset_doc,
	notes,
	date_of_disposal=None,
	date_of_return=None,
	value_after_depreciation=None,
	ignore_booked_entry=False,
):
	for row in asset_doc.get("finance_books"):
		current_asset_depr_schedule_doc = get_asset_depr_schedule_doc(
			asset_doc.name, "Active", row.finance_book
		)

		if not current_asset_depr_schedule_doc:
			frappe.throw(
				_("Asset Depreciation Schedule not found for Asset {0} and Finance Book {1}").format(
					asset_doc.name, row.finance_book
				)
			)

		new_asset_depr_schedule_doc = frappe.copy_doc(current_asset_depr_schedule_doc)

		if asset_doc.flags.increase_in_asset_value_due_to_repair and row.depreciation_method in (
			"Written Down Value",
			"Double Declining Balance",
		):
			new_rate_of_depreciation = flt(
				asset_doc.get_depreciation_rate(row), row.precision("rate_of_depreciation")
			)
			row.rate_of_depreciation = new_rate_of_depreciation
			new_asset_depr_schedule_doc.rate_of_depreciation = new_rate_of_depreciation

		new_asset_depr_schedule_doc.make_depr_schedule(
			asset_doc, row, date_of_disposal, value_after_depreciation=value_after_depreciation
		)
		new_asset_depr_schedule_doc.set_accumulated_depreciation(
			asset_doc, row, date_of_disposal, date_of_return, ignore_booked_entry
		)

		new_asset_depr_schedule_doc.notes = notes

		current_asset_depr_schedule_doc.flags.should_not_cancel_depreciation_entries = True
		current_asset_depr_schedule_doc.cancel()

		new_asset_depr_schedule_doc.submit()


def get_temp_asset_depr_schedule_doc(
	asset_doc, row, date_of_disposal=None, date_of_return=None, update_asset_finance_book_row=False
):
	current_asset_depr_schedule_doc = get_asset_depr_schedule_doc(
		asset_doc.name, "Active", row.finance_book
	)

	if not current_asset_depr_schedule_doc:
		frappe.throw(
			_("Asset Depreciation Schedule not found for Asset {0} and Finance Book {1}").format(
				asset_doc.name, row.finance_book
			)
		)

	temp_asset_depr_schedule_doc = frappe.copy_doc(current_asset_depr_schedule_doc)

	temp_asset_depr_schedule_doc.prepare_draft_asset_depr_schedule_data(
		asset_doc,
		row,
		date_of_disposal,
		date_of_return,
		update_asset_finance_book_row,
	)

	return temp_asset_depr_schedule_doc


@frappe.whitelist()
def get_depr_schedule(asset_name, status, finance_book=None):
	asset_depr_schedule_doc = get_asset_depr_schedule_doc(asset_name, status, finance_book)

	if not asset_depr_schedule_doc:
		return

	return asset_depr_schedule_doc.get("depreciation_schedule")


def get_asset_depr_schedule_doc(asset_name, status, finance_book=None):
	asset_depr_schedule_name = get_asset_depr_schedule_name(asset_name, status, finance_book)

	if not asset_depr_schedule_name:
		return

	asset_depr_schedule_doc = frappe.get_doc("Asset Depreciation Schedule", asset_depr_schedule_name)

	return asset_depr_schedule_doc


def get_asset_depr_schedule_name(asset_name, status, finance_book=None):
	finance_book_filter = ["finance_book", "is", "not set"]
	if finance_book:
		finance_book_filter = ["finance_book", "=", finance_book]

	return frappe.db.get_value(
		doctype="Asset Depreciation Schedule",
		filters=[
			["asset", "=", asset_name],
			finance_book_filter,
			["status", "=", status],
		],
	)


def is_first_day_of_the_month(date):
	first_day_of_the_month = get_first_day(date)

	return getdate(first_day_of_the_month) == getdate(date)
