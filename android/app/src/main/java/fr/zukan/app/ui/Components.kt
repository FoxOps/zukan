package fr.zukan.app.ui

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.zukan.app.R
import fr.zukan.app.data.GameOut

// Building blocks of the 2026-10 redesign (maquettes "Zukan GUI/Android GUI"): pill fields
// and chips, gold actions, grouped settings rows, bottom sheets. Touch targets stay 48 dp
// even where the drawn shape is smaller.

val CardShape = RoundedCornerShape(24.dp)
val FieldShape = RoundedCornerShape(24.dp)
private val RowShape = RoundedCornerShape(16.dp)

/** One of the redesign's line icons (res/drawable/ic_*.xml), in the content colour. */
@Composable
fun ZIcon(@DrawableRes id: Int, contentDescription: String?, modifier: Modifier = Modifier, tint: Color = LocalContentColor.current) {
    Icon(painterResource(id), contentDescription, modifier.size(24.dp), tint = tint)
}

/** Big title, short subtitle and the mascot, on top of each tab. */
@Composable
fun ScreenHeader(title: String, subtitle: String?, modifier: Modifier = Modifier) {
    Row(modifier.fillMaxWidth().padding(top = 16.dp), verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.displaySmall, modifier = Modifier.semantics { heading() })
            subtitle?.let { Text(it, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        Image(painterResource(R.drawable.zukan_mascot), contentDescription = null, modifier = Modifier.size(56.dp))
    }
}

/** Rounded search field with a magnifier and a clear button. */
@Composable
fun PillSearchField(value: String, onValueChange: (String) -> Unit, placeholder: String, modifier: Modifier = Modifier) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        leadingIcon = { ZIcon(R.drawable.ic_search, null) },
        trailingIcon = if (value.isNotEmpty()) {
            { IconButton(onClick = { onValueChange("") }) { ZIcon(R.drawable.ic_close, stringResource(R.string.clear)) } }
        } else {
            null
        },
        singleLine = true,
        shape = FieldShape,
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLow,
            focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerLow,
            unfocusedBorderColor = MaterialTheme.colorScheme.outline,
            focusedBorderColor = MaterialTheme.colorScheme.onSurface,
            unfocusedLeadingIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
            focusedLeadingIconColor = MaterialTheme.colorScheme.onSurface,
            unfocusedPlaceholderColor = MaterialTheme.colorScheme.onSurfaceVariant,
            focusedPlaceholderColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
        modifier = modifier.heightIn(min = 56.dp),
    )
}

/** Square button next to the search field opening the filter sheet; a gold dot when filters apply. */
@Composable
fun FilterButton(active: Boolean, onClick: () -> Unit) {
    val label = stringResource(R.string.filters)
    val state = stringResource(if (active) R.string.filters_on else R.string.filters_off)
    Box(
        Modifier.size(56.dp).clip(FieldShape)
            .background(MaterialTheme.colorScheme.surfaceContainerLow)
            .border(1.dp, MaterialTheme.colorScheme.outline, FieldShape)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics {
                contentDescription = label
                stateDescription = state
            },
        contentAlignment = Alignment.Center,
    ) {
        ZIcon(R.drawable.ic_filter, null)
        if (active) {
            Box(Modifier.align(Alignment.TopEnd).padding(12.dp).size(8.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer))
        }
    }
}

/** Gold when selected, outlined otherwise (games, conditions, colours). */
@Composable
fun PillChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leading: (@Composable () -> Unit)? = null,
) {
    Surface(
        selected = selected,
        onClick = onClick,
        shape = CircleShape,
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
        contentColor = if (selected) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
        border = if (selected) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        modifier = modifier.sizeIn(minWidth = 48.dp, minHeight = 48.dp),
    ) {
        Row(
            Modifier.padding(horizontal = 18.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            leading?.invoke()
            Text(label, style = MaterialTheme.typography.labelLarge, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
        }
    }
}

/** "All games" and the games; past [shown] games a "…" chip opens the filter sheet. */
@Composable
fun GameChips(games: List<GameOut>, selected: String?, onSelect: (String?) -> Unit, onMore: () -> Unit, shown: Int = 2) {
    val visible = games.take(shown).let { first ->
        if (selected != null && first.none { it.id == selected }) first + games.filter { it.id == selected } else first
    }
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        PillChip(stringResource(R.string.any_game), selected == null, { onSelect(null) })
        visible.forEach { g -> PillChip(g.name, selected == g.id, { onSelect(g.id) }) }
        if (games.size > visible.size) {
            val more = stringResource(R.string.more_games)
            PillChip("…", false, onMore, Modifier.semantics { contentDescription = more })
        }
    }
}

/** Uppercase group title ("SCAN AND ADD"). */
@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        letterSpacing = 0.5.sp,
        modifier = modifier.semantics { heading() },
    )
}

/** Rounded card holding settings rows. */
@Composable
fun SettingsGroup(content: @Composable ColumnScope.() -> Unit) {
    Surface(shape = CardShape, color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Column(content = content)
    }
}

/** Setting name with its current value and a chevron; a divider under all but the last. */
@Composable
fun SettingsRow(@DrawableRes icon: Int, title: String, value: String?, onClick: () -> Unit, divider: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onClick).heightIn(min = 72.dp).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ZIcon(icon, null)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontSize = 18.sp)
            value?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        ZIcon(R.drawable.ic_chevron, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (divider) HorizontalDivider(Modifier.padding(start = 56.dp, end = 16.dp), color = MaterialTheme.colorScheme.outline)
}

/** Field-like row opening a list of choices (language, sort, set). */
@Composable
fun PickerRow(text: String, onClick: () -> Unit, @DrawableRes icon: Int? = null, expanded: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().clip(RowShape)
            .background(MaterialTheme.colorScheme.background)
            .border(1.dp, MaterialTheme.colorScheme.outline, RowShape)
            .clickable(role = Role.Button, onClick = onClick)
            .heightIn(min = 56.dp).padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        icon?.let { ZIcon(it, null) }
        Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        ZIcon(R.drawable.ic_chevron, null, Modifier.graphicsLayer { rotationZ = if (expanded) 90f else 0f })
    }
}

/** One option of a list in a sheet: radio (one choice) or checkbox (several). */
@Composable
fun ChoiceRow(text: String, selected: Boolean, onClick: () -> Unit, enabled: Boolean = true, role: Role = Role.RadioButton, subtitle: String? = null) {
    Row(
        Modifier.fillMaxWidth().clip(RowShape)
            .selectable(selected = selected, enabled = enabled, role = role, onClick = onClick)
            .heightIn(min = 52.dp).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = if (selected) FontWeight.SemiBold else null,
                color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            subtitle?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        if (selected) {
            Box(Modifier.size(28.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer), contentAlignment = Alignment.Center) {
                ZIcon(R.drawable.ic_check, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
            }
        }
    }
}

/** − quantity + on a cream pill (48 dp buttons). */
@Composable
fun QuantityStepper(quantity: Int, onMinus: () -> Unit, onPlus: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.clip(RowShape).background(MaterialTheme.colorScheme.background),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onMinus) { ZIcon(R.drawable.ic_minus, stringResource(R.string.less)) }
        Text("$quantity", style = MaterialTheme.typography.titleMedium, modifier = Modifier.sizeIn(minWidth = 20.dp))
        IconButton(onClick = onPlus) { ZIcon(R.drawable.ic_plus, stringResource(R.string.more)) }
    }
}

/** Full-width gold call to action. */
@Composable
fun GoldButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ctaColors(),
        shape = FieldShape,
        modifier = modifier.fillMaxWidth().heightIn(min = 56.dp),
    ) { Text(text, style = MaterialTheme.typography.titleMedium, fontSize = 18.sp) }
}

/** Bottom sheet with a title, a close button, scrolling content and an optional footer. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ZukanSheet(
    title: String,
    onDismiss: () -> Unit,
    subtitle: String? = null,
    footer: (@Composable ColumnScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
    ) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp).navigationBarsPadding()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f).semantics { heading() })
                IconButton(onClick = onDismiss) { ZIcon(R.drawable.ic_close, stringResource(R.string.close)) }
            }
            subtitle?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Spacer(Modifier.size(16.dp))
            Column(
                Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(20.dp),
                content = content,
            )
            footer?.let {
                Column(Modifier.padding(vertical = 16.dp), horizontalAlignment = Alignment.CenterHorizontally, content = it)
            }
            if (footer == null) Spacer(Modifier.size(24.dp))
        }
    }
}

/** Titled block inside a sheet. */
@Composable
fun SheetSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontSize = 18.sp, modifier = Modifier.semantics { heading() })
        content()
    }
}

/** Reset (text) and apply (gold) at the bottom of a filter sheet. */
@Composable
fun ColumnScope.FilterFooter(onReset: () -> Unit, onApply: () -> Unit) {
    TextButton(onClick = onReset, modifier = Modifier.heightIn(min = 48.dp)) {
        Text(stringResource(R.string.reset_filters), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
    }
    Spacer(Modifier.size(8.dp))
    GoldButton(stringResource(R.string.apply_filters), onApply)
}

/** Rounded card for empty and error states. */
@Composable
fun MessageCard(title: String, text: String?, modifier: Modifier = Modifier, picture: (@Composable () -> Unit)? = null, action: (@Composable () -> Unit)? = null) {
    Surface(shape = CardShape, color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            picture?.invoke()
            Text(title, style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
            text?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
            action?.invoke()
        }
    }
}

/** Cardmarket condition code on a sand tag. */
@Composable
fun ConditionTag(code: String) {
    Box(
        Modifier.clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.outlineVariant).padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(code, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurface)
    }
}

/** Cardmarket grading names (the same words in every language on Cardmarket). */
val CONDITION_NAMES = mapOf(
    "MT" to "Mint", "NM" to "Near Mint", "EX" to "Excellent", "GD" to "Good",
    "LP" to "Light Played", "PL" to "Played", "PO" to "Poor",
)
